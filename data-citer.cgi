#!/opt/local/bin/perl

#   !/usr/bin/perlml
use strict;
use warnings;
use utf8;

use CGI::Simple;
my $q = CGI::Simple->new;
$q->charset('utf-8');      # set the charset

use Encode;
use LWP::UserAgent;
use HTML::TokeParser::Simple;
use Date::Parse::Lite;
use JSON;
use Text::Names qw(parseName);
use open qw( :encoding(UTF-8) :std );
open(STDERR, ">&STDOUT");

$CGI::Simple::POST_MAX=1024 * 100;  # max 100K posts
$CGI::Simple::DISABLE_UPLOADS = 1;  # no uploads

my $tool_url = $q->url();
( my $doi  = $q->param('DOI')    ) =~ s/\s+//g;
( my $acc  = $q->param('ACC')    ) =~ s/\s+//g;
( my $repo = $q->param('repoRF') ) =~ s/\s+//g;
( my $prov = $q->param('PROV')   ) =~ s/\s+//g;
my $cut = 5;       # defines length at which author lists are truncated with et al. 
my $year = "????"; # defines default text for 'year' field
my $contact_email = 'contact@alhufton.com';
my $json = JSON::PP->new->pretty;  # creates a json parsing object

# Define core metadata fields to be filled
my ($title, $authors, $date, $publisher, $id);
my ($source_url, $source_metadata, $source_name);

binmode(STDOUT, ":utf8");
print "Content-Type: text/html; charset=utf-8\n\n"; 

start_html("Data Citation Formatter");
print_header();
print_prompt();
do_work();
print_tail();

exit;

sub do_work {
    
    #print "<h2>Here are the current settings in this form</h2>\n";
    #for my $key ($q->param()) {
    #    print "<strong>$key</strong> -> ";
	#    my @values = $q->param($key);
	#    print join(", ",@values),"<br>\n";
	#}

    # If user provided an accession number & repo prefix
    if ($acc && $repo) {
        
        # This section builds a identifiers.org URL
        my $data_url = &build_url_acc();
        $id = $data_url; 

        # Try to get information from the HTML
        &get_html_metadata( $data_url ); 
        
        if ($date) {
            my $date_parser = Date::Parse::Lite->new();
            $date_parser->parse($date);
 
            if ( $date_parser->parsed() ) {
                $year = $date_parser->year();
            }
        }
        
        # Get publisher name from identifiers.org API if it was in the HTML
        &get_publisher_i_org() unless $publisher; 

    # Or if a DOI was provided
    } elsif ( $doi ) {
            # clean & check for a valid DOI
            $doi =~ s/^doi:[\s]*//;
            $doi =~ s/^https*:\/\/doi\.org\///;
            $doi =~ s/^https*:\/\/dx\.doi\.org\///;
            unless ( $doi =~ /^10\./ ) { print "Invalid DOI provided: $doi.\n\n"; exit; }
            
            $id = "https://doi.org/$doi"; 
            &get_datacite_metadata( $doi );
    } else {
        return;
    }
    
    &fail unless ($publisher);
    
    # Create the results section
    my $citation = &citation_nature();
    print "<div class=\"results\">\n";
    print "<h3>Data citation information found via $source_name:</h3>\n";
    print "<p>$citation</p>\n\n" if $citation;
    print "</div>\n";
    
    # Create a details tab
    if ( $source_metadata ) {
        print <<EOF;
    
<div class="wrap-collabsible">
    <input id="collapsible" class="toggle" type="checkbox">
    <label for="collapsible" class="lbl-toggle">Details</label>
    <div class="collapsible-content">
        <div class="content-inner">
            <p>Metadata obtained from <a href=\"$source_url\">$source_url</a></p>
            <p><pre>$source_metadata</pre></p>
        </div>
    </div>
</div>

EOF
    }        
}

# Build a URL according to the rules defined in https://doi.org/10.1038/sdata.2018.29
sub build_url_acc {
    my $url;
    if ($prov) { $url = "https://identifiers.org/$prov/$repo:$acc" }
    else { $url = "https://identifiers.org/$repo:$acc"}
    print STDERR "url: $url\n";
    return $url;
}

sub get_publisher_i_org {
    my $ua = LWP::UserAgent->new;
    $ua->timeout(60);
    my $namespaceID;
   
    my $response = $ua->get("https://registry.api.identifiers.org/restApi/namespaces/search/findByPrefix?prefix=$repo");
    if ($response->is_success) {
        my $metadata = decode_json $response->content;
        $publisher = $metadata->{name};
        if ( $metadata->{_links}->{namespace}->{href} =~ /https:\/\/registry\.api\.identifiers\.org\/restApi\/namespaces\/([0-9]+)/) {
            $namespaceID = $1; 
        }
    } else {
        print $response->status_line; exit;
    }
    if ($prov) {
        #print "trying https://registry.api.identifiers.org/restApi/resources/search/findByNamespaceIdAndProviderCode?namespaceId=$namespaceID&providerCode=$prov\n\n";
        $response = $ua->get("https://registry.api.identifiers.org/restApi/resources/search/findByNamespaceIdAndProviderCode?namespaceId=$namespaceID&providerCode=$prov");
        if ($response->is_success) {
            #print $response->content;
            my $metadata = decode_json $response->content;
            $publisher = $metadata->{_embedded}->{resources}->[0]->{name};
        } else {
            print $response->status_line; exit;
        }
    }
    unless ($source_name) { $source_name = 'identifiers.org API'; }
    else { $source_name .= ' & identifiers.org API';}
}

   
# Get DataCite metadata from a provided DOI
sub get_datacite_metadata {
    my $datacite_doi = shift;
    my $ua = LWP::UserAgent->new;
    $ua->timeout(30);
    my $agency_url = "https://api.crossref.org/works/$datacite_doi/agency";
    $source_url = "https://data.datacite.org/application/vnd.datacite.datacite+json/$datacite_doi"; 
   
    # Is this a DataCite DOI?
    my $response = $ua->get($agency_url);
    if ($response->is_success) {
        my $agency_check = $json->decode($response->content);
        unless ( $agency_check->{message}->{agency}->{id} eq 'datacite' ) {
            print "\n\nProvided DOI is not registered with DataCite.\n\n"; exit;
        }
    } else {
        print $response->status_line; exit;
    }
    
    # Ok, get the DataCite metadata
    $response = $ua->get($source_url);
    if ($response->is_success) {
        #print $response->content;
        my $metadata = decode_json $response->content;
        my @authors; 
        foreach my $element ( @{$metadata->{creators}} ) {
            unless ($element->{nameType} eq 'Organizational') {
                $element->{name} =~ s/\(.*?\)//g; # Delete anything within parentheses (hack to deal with some pathological DataCite examples)
                push @authors, &name_parser_punc($element->{name});
            } else {
                push @authors, $element->{name};
            }
        }

        $authors         = \@authors;
        $publisher       = $metadata->{publisher};
        $title           = $metadata->{titles}->[0]->{title};
        $year            = $metadata->{publicationYear};
        $source_name     = 'DataCite';
        $source_metadata = $json->encode($metadata);
    } else {
        print $response->status_line; &fail; exit;
    }
}

# Get metadata from a target URL
sub get_html_metadata {
    my $url = shift;
    
    #print "<p>Trying to obtain metadata from $url</p>\n";
    
    my $ua = LWP::UserAgent->new;
    $ua->timeout(10);
    my $response = $ua->get($url);
    #print $response->as_string;
    my $html = $response->decoded_content;
    my @authors;
    
    if ($response->is_success) {
        
        my $p = HTML::TokeParser::Simple->new( \$html );
     
        my $i = 0; 
        while ( my $token = $p->get_token ) {
            # Identify linked data
            if ( $token->is_start_tag('script') && $token->get_attr('type') && $token->get_attr('type') eq 'application/ld+json') {
                my $script = $p->get_token;
                my $metadata = $json->decode($script->as_is);
                my $mtype = lc $metadata->{'@type'}; 
                
                # This needs to be rewritten to allow for cases where any or all 
                # properties are arrays (see BCO-DMO), and to check the mainEntity
                # if the top level fails. This will also us to also remove the
                # special OmicsDI parsing. There is little value in pulling the 
                # publisher name from citation anyways, so the special citation case
                # can be eliminated. Probably good to have separate subroutines 
                # for grabbing single properties (check that property exists, check
                # for array, then pull and return properly).
                
                if ( $mtype eq 'dataset' || $mtype eq 'datarecord' ) {
                    ++$i;

                    if ( $metadata->{'name'}                ) { $title = $metadata->{'name'} }
                    if ( $metadata->{'publisher'}->{'name'} ) { $publisher = $metadata->{'publisher'}->{'name'} }
                    if ( $metadata->{'datePublished'}       ) { $date = $metadata->{'datePublished'} }
                    
                    if ( $metadata->{creator} ) {
                        foreach my $element ( @{$metadata->{creator}} ) {
                            my $name; 
                            if ( $element->{familyName} && $element->{givenName} ) {
                                $name = $element->{familyName} . ", " . $element->{givenName};
                            } else {
                                $name = $element->{name} 
                            }
                            $name = &name_parser_punc($name) if ($element->{'@type'} eq 'Person');
                            push @authors, $name;
                        }
                    }
                    $authors = \@authors;
                    
                    $source_name = 'schema.org';
                    $source_url  = $url;
                    $source_metadata = $json->encode($metadata);

                # special parsing for OmicsDI
                } elsif ( $mtype eq 'itempage' ) {
                    $mtype = lc $metadata->{mainEntity}->{'@type'};
                    if ( $mtype eq 'dataset' || $mtype eq 'datarecord' ) {
                    
                        ++$i;

                        if ( $metadata->{mainEntity}->{'name'} )                            { $title     = $metadata->{mainEntity}->{'name'} }
                        if ( $metadata->{mainEntity}->{citation}->{'publisher'}->{'name'} ) { $publisher = $metadata->{mainEntity}->{citation}->{'publisher'}->{'name'} }
                        if ( $metadata->{mainEntity}->{'datePublished'} )                   { $date      = $metadata->{mainEntity}->{'datePublished'} }
                    
                        if ( $metadata->{mainEntity}->{creator} ) {
                            foreach my $element ( @{$metadata->{mainEntity}->{creator}} ) {
                                my $name; 
                                if ( $element->{familyName} && $element->{givenName} ) {
                                    $name = $element->{familyName} . ", " . $element->{givenName};
                                } else {
                                    $name = $element->{name} 
                                }
                                $name = &name_parser_punc($name) if ($element->{'@type'} eq 'Person');
                                push @authors, $name;
                            }
                        }
                        $authors = \@authors;
                    
                        $source_name = 'schema.org via OmicsDI';
                        $source_url  = $url;
                        $source_metadata = $json->encode($metadata);
                    }
                }
            }
        }
        if ($i > 1) { print "<p><strong>Warning:</strong> ld+json metadata found for more than one dataset.</p>\n";}
        
    } else {
        print "<p>Invalid URL: $url</br>" . $response->status_line . "</p>\n";
        &fail;
        exit;
    }   
}

# Formats names as lastname, initials with full punctuation. 
sub name_parser_punc {
    my $input = shift;
    my @name = parseName($input); 
    my $initials = "";
    foreach my $element ( split(/\s/, $name[0]) ) {
        $initials .= substr($element, 0, 1) . ". ";
    }
    $initials =~ s/\s$//;
    my $formatted_name = $name[1] . ", " . $initials;
    return $formatted_name; 
}

# Format a citation string according to the Nature Research style
sub citation_nature {
    
    my $citation;
    
    # Define and check for required fields
    unless ($publisher && $id && $year) {
        &fail();
        return;
    }
    
    # Print a standard citation
    my $author_line = "";
 
    if ( $authors ) {
        my $k = @{$authors}; 
        if ($k > 0 ) {
            if ($k >= $cut) {
                $author_line = $authors->[0] . " et al."
            } else {
                my $i = 0;
                my $connect = ", ";
                foreach my $author ( @{$authors} ) {
                    ++$i; 
                    if ($i == $k - 1) { $connect = " & "; }
                    if ($i == $k) { $connect = ""; }
                    $author_line .= $author . $connect;
                }
                $author_line .= "." unless ( $author_line =~ /\.$/ );
            }
            $citation = "$author_line ";
        }
    }
    $citation .= "$title. " if $title;
    $citation .= "<em>$publisher</em> " if $publisher;
    $citation .= "<a href=\"$id\">$id</a> " if $id;
    $citation .= "($year)." if $year;
    $citation =~ s/\s$//;
    return $citation;
}

# Basic subroutines to start and end the webpage
sub start_html {
    print <<EOF;
    
<head>
<title>Data Citation Formatter</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* {
  box-sizing: border-box;
}

body {
  font-family: Arial, Helvetica, sans-serif;
  color: #3f3f3f;
}

/* Style the header */
.header {
  color: #1e73be;
  background-color: white;
  padding: 10px;
  margin: 0px;
  line-height: 0px;
  text-align: left;
  font-size: 18px;
}

/* Style the intro */
.intro {
  padding: 10px;
  text-align: left;
}

/* Style the results */
.results {
  background-color: #ADD8E6;
  padding: 10px;
  text-align: left;
}

.results h3, .results h2, .results h4 {
  color: #1e73be;
}

/* Create three equal columns that floats next to each other */
.column {
  float: left;
  width: 50\%;
  padding: 10px;
  height: 140px;
}

/* Clear floats after the columns */
.row:after {
  content: "";
  display: table;
  clear: both;
}

/* Style the footer */
.footer {
  color: #3f3f3f;
  background-color: #eaeaea;
  padding: 10px;
  text-align: right;
}

/* Responsive layout - makes the three columns stack on top of each other instead of next to each other */
\@media (max-width: 600px) {
  .column {
    width: 100\%;
  }
}

.wrap-collabsible {
  margin-bottom: 1.2rem 0;
}

input[type='checkbox'] {
  display: none;
}

.lbl-toggle {
  display: block;

  font-weight: bold;
  font-size: 1.2rem;
  text-align: center;

  padding: 1rem;

  color: #A77B0E;
  background: #FAE042;

  cursor: pointer;

  border-radius: 7px;
  transition: all 0.25s ease-out;
}

.lbl-toggle:hover {
  color: #7C5A0B;
}

.lbl-toggle::before {
  content: ' ';
  display: inline-block;

  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-left: 5px solid currentColor;
  vertical-align: middle;
  margin-right: .7rem;
  transform: translateY(-2px);

  transition: transform .2s ease-out;
}

.toggle:checked + .lbl-toggle::before {
  transform: rotate(90deg) translateX(-3px);
}

.collapsible-content {
  max-height: 0px;
  overflow: hidden;
  transition: max-height .25s ease-in-out;
}

.toggle:checked + .lbl-toggle + .collapsible-content {
  max-height: 10000vh;
}

.toggle:checked + .lbl-toggle {
  border-bottom-right-radius: 0;
  border-bottom-left-radius: 0;
}

.collapsible-content .content-inner {
  background: rgba(250, 224, 66, .2);
  border-bottom: 1px solid rgba(250, 224, 66, .45);
  border-bottom-left-radius: 7px;
  border-bottom-right-radius: 7px;
  padding: .5rem 1rem;
}

</style>
</head>
<body>
    
EOF

}

sub print_header {
    print "<div class=\"header\"><h1>Data Citation Formatter</h1></div>\n";
    print "<div class=\"intro\">\n";
    unless (($acc && $repo) || $doi ) {
        &print_intro;
    } else {
        print "<p>Search for citation information for another dataset.</p>
        <p><a href=\"$tool_url\">Clear form</a></p>\n";
    }
    print "</div>\n";
}

sub print_tail {
    print <<EOF;
    
<div>&nbsp;</div>    
<div class="footer">
<p><a href="https://alhufton.com/">Home</a> | <a href=\"mailto:$contact_email\">Contact</a> | GitHub </p>
<p>© 2020 Andrew Lee Hufton</p>
</div>
</body>
</html>

EOF

}

sub fail {
    print <<EOF;
    
<p>Citation metadata not found for <a href="$id">$id</a>.</p>
    
<p>Please note that this tool currently only supports citation metadata provided 
through DataCite (for DOIs) and Schema.org (for accession ids). Do you know of 
a data repository using another standard to provide machine-readable citation 
metadata? <a href="mailto:$contact_email">Email me an example</a>.</p>
    
EOF

&print_tail;

exit;
    
}
    
sub print_intro {
    print <<EOF;

<p>This webform attempts to construct a formatted data citation from a DataCite 
DOI or an identifiers.org registered accession number. Citation information for 
DOIs is obtained from the <a href="https://support.datacite.org/docs/api">DataCite API</a>. 
For accession numbers, an identifiers.org URL is constructed, resolved to the 
target webpage, and then the page is searched for schema.org metadata tags. The 
latter is poorly tested and not likely to work in most cases. 
If you know of identifiers.org data records with good, machine-readable citation 
metadata, please <a href="mailto:$contact_email">let me know</a>. Formatting follows
the Nature Research style. For more information on
scholarly data citation standards please see 
<a href="https://doi.org/10.1038/sdata.2018.29">Wimalaratne et al.</a>, 
<a href="https://doi.org/10.1038/s41597-019-0031-8">Fenner et al.</a>, 
and <a href="https://doi.org/10.1038/sdata.2018.259">Cousijn et al.</a> Try these 
examples: <a href="$tool_url?DOI=&repoRF=pride.project&ACC=PXD001416&PROV=omicsdi">PXD001416 via OmicsDI</a>,
<a href="$tool_url?DOI=https%3A%2F%2Fdoi.org%2F10.14284%2F350&repoRF=&ACC=&PROV=">https://doi.org/10.14284/350</a>, 
<a href="$tool_url?DOI=&repoRF=pdb&ACC=2gc4&PROV=pdbe">2gc4 via PDBe</a>.
</p> 
        
<p><strong>Note:</strong> this is a personal project, and not a service provided 
by <a href="https://www.nature.com/nature-research">Nature Research</a> or 
<em><a href="https://nature.com/sdata/">Scientific Data</a></em>.</p>
<p><strong>Latest updates</strong>: Schema.org support and a new Details section.</p>

EOF

}

sub print_prompt {
    print <<EOF;

<form> 
<div class="row">
  <div class="column" style="background-color:#aaa;">
    <strong>Enter a dataset DOI</strong><br>
    
EOF

    if ($doi) { print "<input type=\"text\" name=\"DOI\" value=\"$doi\"><br>\n";}
    else { print "<input type=\"text\" name=\"DOI\"><br>\n"; }
        
    print <<EOF;
    
    Dataset must be registered with <a href="https://datacite.org/">DataCite</a>
  </div> 
  <div class="column" style="background-color:#bbb;">
    <strong>Or, enter a repository prefix and a valid accession identifier.</strong></br>
	See <a href="https://n2t.net/e/cdl_ebi_prefixes.yaml">here</a> for supported prefixes and providers</br>
	
EOF
	
	if ($repo) { print "Prefix:&nbsp;<input type=\"text\" name=\"repoRF\" value=\"$repo\"></br>"; }
	else { print "Prefix:&nbsp;<input type=\"text\" name=\"repoRF\"></br>"; }
	
	if ($acc) { print "Accession:&nbsp;<input type=\"text\" name=\"ACC\" value=\"$acc\"></br>"; }
	else { print "Accession:&nbsp;<input type=\"text\" name=\"ACC\"></br>"; }
	
	if ($prov) { print "Provider&nbsp;(optional):&nbsp;<input type=\"text\" name=\"PROV\" value=\"$prov\">"; }
	else { print "Provider&nbsp;(optional):&nbsp;<input type=\"text\" name=\"PROV\">"; }
	    
	print <<EOF;
	    
  </div>
</div>
<div class="button"><input type="submit" value="Get data citation" style="font-size : 20px;"></div>
</form>
	
EOF

}