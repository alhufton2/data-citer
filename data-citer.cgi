#!/opt/local/bin/perl

# use the shebang line below when running at bluehost
#   !/usr/bin/perlml

use strict;
use warnings;
use utf8;

use CGI::Carp qw(fatalsToBrowser set_message);
BEGIN {
   sub handle_errors {
      my $msg = shift;
      print "<h1>A serious error occurred</h1>";
      print "<p>The following error message was generated: $msg</p>";
  }
  set_message(\&handle_errors);
}

# Load CGI webform package and create a handler
use CGI::Simple;
my $q = CGI::Simple->new;
$q->charset('utf-8');      # set the charset

# Load other packages
use CHI; 
use Encode;
use LWP::UserAgent;
use HTML::TokeParser::Simple;
use Date::Parse::Lite;
use JSON::PP;
use Text::Names qw(parseName);
use open qw( :encoding(UTF-8) :std );

# Read in any CGI parameters and clean whitespace
my $tool_url = $q->url();
my $doi  = $q->param('DOI');
$doi =~ s/\s+//g if $doi;
my $acc  = $q->param('ACC');
$acc =~ s/\s+//g if $acc;
my $repo = $q->param('repoRF');
$repo =~ s/\s+//g if $repo;
my $prov = $q->param('PROV');
$prov =~ s/\s+//g if $prov;
my $prefer_schema = $q->param('prefer_schema');

# Open the cache
my $cache = CHI->new( driver => 'File' );

# Set various variables
my $cut = 5;       # defines length at which author lists are truncated with et al. 
my $year = "????"; # defines default text for 'year' field
my $contact_email = 'contact@alhufton.com';
my $timeout = 30;
my $cache_time = '30';
my $json = JSON::PP->new->pretty;  # creates a json parsing object

# Define core metadata fields to be filled
my ($title, $date, $publisher, $id);
my %source; # has fields url, metadata and name
my @authors;
my @warnings;

binmode(STDOUT, ":utf8");

# Main body 
print "Content-Type: text/html; charset=utf-8\n\n";
start_html();
print_header();
print_prompt();
do_work();
print_tail();

exit;

sub do_work {
    my $cache_id;

    # Build the ID
    if ($acc && $repo) {
        
        if ($prov) { $id = "https://identifiers.org/$prov/$repo:$acc" }
        else { $id = "https://identifiers.org/$repo:$acc"}
        $cache_id = $id; 

    } elsif ( $doi ) {
        
        # clean & check for a valid DOI
        $doi =~ s/^doi:[\s]*//;
        $doi =~ s/^https*:\/\/(dx\.)*doi\.org\///;
        unless ( $doi =~ /^10\./ ) { print "Invalid DOI provided: $doi.\n\n"; &print_tail; exit; }
        $id = "https://doi.org/$doi"; 
        if ( $prefer_schema ) { $cache_id = "schema" . $id; }
        else { $cache_id = $id; }
        
    } else {
        return;
    }
    
    # Check for a cached result
    my $cache_results = $cache->get($cache_id);
    if ( defined $cache_results ) {
        print $cache_results;
        return;
    }
    
    # If not cached, now try to get metadata
    if ( $acc && $repo ) { 

        # Try to get information from the HTML
        &get_html_metadata( $id ); 
                
        # Get publisher name from identifiers.org API if it was in the HTML
        &get_publisher_i_org() unless $publisher; 

    } elsif ( $doi ) {
        # Try DataCite or Crossref, with fall back to target HTML
        if ( $prefer_schema ) { &get_html_metadata( $id ); }
        unless ( $source{metadata} ) { &get_doi_metadata; }
        
    }

    &fail unless ($publisher);
    
    # Build the results    
    my $citation = &citation_nature();
    my $results = &make_results($citation);
    $results .= &make_details if $source{metadata};
    
    print $results;
    $cache->set($cache_id, $results, $cache_time);
}

# Attempts to retrieve the publisher name from the identifiers.org API
sub get_publisher_i_org {
    my $ua = LWP::UserAgent->new;
    $ua->timeout($timeout);
    my $namespaceID;
   
    my $response = $ua->get("https://registry.api.identifiers.org/restApi/namespaces/search/findByPrefix?prefix=$repo");
    if ($response->is_success) {
        my $metadata = decode_json $response->content;
        $publisher = $metadata->{name};
        if ( $metadata->{_links}->{namespace}->{href} =~ /https:\/\/registry\.api\.identifiers\.org\/restApi\/namespaces\/([0-9]+)/) {
            $namespaceID = $1; 
        }
    } else {
        print $response->status_line; &print_tail; exit;
    }
    
    # If a provider was declared, try to get the more specific publisher name
    if ($prov) {
        $response = $ua->get("https://registry.api.identifiers.org/restApi/resources/search/findByNamespaceIdAndProviderCode?namespaceId=$namespaceID&providerCode=$prov");
        if ($response->is_success) {
            my $metadata = decode_json $response->content;
            $publisher = $metadata->{_embedded}->{resources}->[0]->{name};
        } else {
            print $response->status_line; &print_tail; exit;
        }
    }
    unless ($source{name}) { $source{name} = 'identifiers.org API'; }
    else { $source{name} .= ' & identifiers.org API';}
}

   
# Get DataCite metadata from a provided DOI
sub get_doi_metadata {

    my $ua = LWP::UserAgent->new;
    $ua->timeout($timeout);
    my $agency;
   
    # Get DOI agency
    my $response = $ua->get("https://api.crossref.org/works/$doi/agency");
    if ($response->is_success) {
        my $agency_message = $json->decode($response->content);
        $agency = $agency_message->{message}->{agency}->{id};
    } else {
        print $response->status_line; &fail;
    }
    
    # If not a DataCite or Crossref DOI, warn and try to get Schema.org metadata
    if ( $agency ne 'datacite' && $agency ne 'crossref' ) {
        
        push @warnings, "DOI agency was neither DataCite nor Crossref: $agency.";
        &get_html_metadata($id);
        
    } elsif ( $agency eq 'datacite' ) {

        # Get DataCite metadata
        $source{url} = "https://data.datacite.org/application/vnd.datacite.datacite+json/$doi"; 
        $response = $ua->get($source{url});
        if ($response->is_success) {
    
            my $metadata = decode_json $response->content;
            foreach my $element ( @{$metadata->{creators}} ) {
                if ($element->{nameType} eq 'Personal' || $element->{familyName} ) {
                    # Delete anything within parentheses (hack to deal with some pathological DataCite examples)
                    $element->{name} =~ s/\(.*?\)//g; 
                    push @authors, &name_parser_punc($element->{name});
                } else {
                    push @authors, $element->{name};
                }
            }
    
            $publisher       = $metadata->{publisher};
            $title           = $metadata->{titles}->[0]->{title};
            $year            = $metadata->{publicationYear};
            $source{name}     = 'DataCite';
            $source{metadata} = $json->encode($metadata);
        } else {
            print $response->status_line; &fail;
        }
    } elsif ( $agency eq 'crossref' ) {
        
        # Get Crossref metadata
        $source{url} = "https://api.crossref.org/works/$doi";
        $response = $ua->get($source{url});
        if ($response->is_success) {
    
            my $metadata = decode_json $response->content;
            unless ( $metadata->{message}->{type} eq 'dataset' ) {
                print "<p>Error: Digital object is not registered at Crossref as a dataset ($metadata->{message}->{type}).</p>";
                &print_tail; exit;
            }
            
            foreach my $element ( @{$metadata->{message}->{author}} ) {
                if ( $element->{family} && $element->{given} ) {
                    my $name = $element->{family} . ", " . $element->{given};
                    push @authors, &name_parser_punc($name);
                } else {
                    push @authors, $element->{name};
                }
            }
    
            $publisher       = $metadata->{message}->{publisher};
            $title           = $metadata->{message}->{title}->[0];
            $year            = $metadata->{message}->{issued}->{'date-parts'}->[0]->[0];
            $source{name}     = 'Crossref';
            $source{metadata} = $json->encode($metadata);
        } else {
            print $response->status_line; &fail;
        }
    }
  
}

# Get metadata from a target URL
sub get_html_metadata {
    my $url = shift;
    
    my $ua = LWP::UserAgent->new;
    $ua->timeout($timeout);
    my $response = $ua->get($url);
    my $html = $response->decoded_content;
    
    if ($response->is_success) {
        
        my $p = HTML::TokeParser::Simple->new( \$html );
        my $i = 0; 
        my $use_metadata;
        
        while ( my $token = $p->get_token ) {
            # Identify linked data
            if ( $token->is_start_tag('script') && $token->get_attr('type') && $token->get_attr('type') eq 'application/ld+json') {
                my $script = $p->get_token;
                my $metadata = $json->decode($script->as_is); 
                
                if ( lc $metadata->{'@type'} eq 'dataset' || lc $metadata->{'@type'} eq 'datarecord' ) {
                    unless ($i > 0)  { $use_metadata = $metadata }
                    ++$i;
                    
                } elsif ( $metadata->{mainEntity} && (lc $metadata->{mainEntity}->{'@type'} eq 'dataset' || lc $metadata->{mainEntity}->{'@type'} eq 'datarecord' )) {
                    unless ($i > 0)  { $use_metadata = $metadata->{mainEntity}; }
                    ++$i;
                }
            }
        }        
        
        if ($i > 0) {
            &parse_Schema_dataset( $use_metadata );
            $source{name} = 'schema.org';
            $source{url}  = $url;
            $source{metadata} = $json->encode($use_metadata);
        }
        if ($i > 1) { 
            push @warnings, "Schema.org metadata found for more than one DataSet or DataRecord. Only the first was used.";
        }
        if ($date) {
            my $date_parser = Date::Parse::Lite->new();
            $date_parser->parse($date);
 
            if ( $date_parser->parsed() ) {
                $year = $date_parser->year();
            } else { 
                $year = $date;
                push @warnings, "Date ($date) was not successfully parsed.";
            }
        }
        
    } else {
        print "<p>Invalid URL: $url</br>" . $response->status_line . "</p>\n";
        &fail;
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
    my $formatted_name = $name[1] . ", " . $initials;
    $formatted_name =~ s/[\s,]+$//;
    return $formatted_name; 
}

# Parses a provided Schema.org DataSet or DataRecord object
sub parse_Schema_dataset {
    my $metadata = shift;
    
    # These need to be checked for arrays
    $title     = &assign( $metadata, 'name' );
    $publisher = &assign2( $metadata, 'publisher', 'name' );
    $date      = &assign( $metadata, 'datePublished' );
    
    # probably an array but not always
    if ( $metadata->{creator} ) {
        
        # Check if it is an array, if not create a single element array
        my @temp_array;
        if ( ref $metadata->{creator} eq ref [] ) {
            @temp_array = @{$metadata->{creator}};
        } else {
            push @temp_array, $metadata->{creator};
        }
        
        # Ok now parse all the names in the array
        foreach my $element ( @temp_array ) {
            my $name; 
            if ( $element->{familyName} && $element->{givenName} ) {
                $name = $element->{familyName} . ", " . $element->{givenName};
            } else {
                $name = $element->{name} 
            }
            $name = &name_parser_punc($name) if ( $element->{familyName} || $element->{'@type'} eq 'Person');
            push @authors, $name;
        }
    } 
}

sub assign {
    my $metadata = shift;
    my $property = shift; 
    
    if ( $metadata->{$property} ) {

        return $metadata->{$property} if ( ref $metadata->{$property} eq '' ); # check that there isn't another reference layer
        if ( $metadata->{$property}->[0] ) {
            push @warnings, "Array encountered for property, '$property', expected to have unique value.";
            return $metadata->{$property}->[0] if ( ref $metadata->{$property}->[0] eq '' );
        }
    }
    return undef;
}

sub assign2 {
    my $metadata = shift;
    my $property = shift; 
    my $property2 = shift;
    
    if ( $metadata->{$property} ) {
        if ( ref $metadata->{$property} eq ref []  ) {
            push @warnings, "Array encountered for property, '$property', expected to have unique value.";
            return $metadata->{$property}->[0]->{$property2} if ( $metadata->{$property}->[0]->{$property2} );
        } else {
            return $metadata->{$property}->{$property2} if ( $metadata->{$property}->{$property2} );
        }
    }
    return undef;
}
    

# Format a citation string according to the Nature Research style
sub citation_nature {
    
    my $citation;
    
    # Define and check for required fields
    unless ($publisher && $id && $year) {
        &fail;
    }
    
    # Print a standard citation
    my $author_line = "";
 
    if ( @authors ) {
        my $k = @authors; 
        if ($k > 0 ) {
            if ($k >= $cut) {
                $author_line = $authors[0] . " et al."
            } else {
                my $i = 0;
                my $connect = ", ";
                foreach my $author ( @authors ) {
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
    $citation .= "($year).";
    return $citation;
}

############################
# HTML writing subroutines #
############################

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
  font-family: Verdana, Geneva, sans-serif;;
  color: #999;
  background-color: black;
  max-width:1020px;
  margin: auto;
  width: 100vw;
  padding: 10px;

}

a, a:visited {
    color: white;
    text-decoration: none;
}

a:hover {
    color: lightblue;
}

/* Style the header */
.header {
  font-family: Arial, Helvetica, sans-serif;
  color: #DEB887;
  background-color: black;
  padding: 5px;
  margin: 0px;
  line-height: 0px;
  text-align: left;
  font-size: 16px;
}

.header a {
  text-decoration: none;
  color: #DEB887;
}

/* Style the intro */
.intro {
  padding: 10px;
  text-align: justify;
  font-size: 14px;
}

/* Style the results */
.results {
  padding: 10px;
  text-align: left;
}

.results h3, .results h2, .results h4 {
  color: #70db70;
  font-weight: normal;
  margin-top: 0;
}

.button {
  padding: 10px;
}

/* Create three equal columns that floats next to each other */
.row {
  border-top: 1px solid;
  border-bottom: 1px solid;
}

.column {
  float: left;
  width: 50\%;
  padding: 10px;
}

.column h2, h3, h4 {
  margin-top: 0; 
  color: #70db70;
  font-weight: normal;
}

/* Clear floats after the columns */
.row:after {
  content: "";
  display: table;
  clear: both;
}

/* Style the footer */
.footer {
  padding: 10px;
  text-align: right;
  border-top: 1px solid;
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

  background: #606060;
  color: #D3D3D3; 

  cursor: pointer;

  border-radius: 7px;
  transition: all 0.25s ease-out;
}

.lbl-toggle:hover {
  color: #66ff66;
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
  background: #4d3900;
  color: #fff2cc;
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
    print "<div class=\"header\"><h1><a href=\"$tool_url\">Data Citation Formatter</a></h1></div>\n";
    print "<div class=\"intro\">\n";
    unless (($acc && $repo) || $doi ) {
        &print_intro;
    } 
    print "</div>\n";
}

sub print_tail {
    print <<EOF;
    
<div>&nbsp;</div>    
<div class="footer">
<p><a href="https://alhufton.com/">Home</a> 
| <a href="mailto:$contact_email">Contact</a> 
| <a href="https://github.com/alhufton2/data-citer">GitHub</a></p>
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
through DataCite, Crossref and Schema.org. Do you know of 
a data repository using another standard to provide machine-readable citation 
metadata? <a href="mailto:$contact_email">Email me an example</a>.</p>
    
EOF

    &print_tail;

    exit;
    
}
    
sub print_intro {
    print <<EOF;

<p>This webform attempts to construct a formatted data citation from a 
DOI or an <a href="identifiers.org/">identifiers.org</a> registered accession 
number. Citation information is obtained from the <a href="https://datacite.org/">DataCite</a> 
or <a href="https://www.crossref.org/">Crossref</a> APIs, or, failing that, by 
trying to search the target page for <a href="https://schema.org/">Schema.org</a> 
metadata. Only Schema.org metadata in JSON-LD is currently 
supported. For identifiers.org datasets, a repository name is obtained from the 
<a href="https://docs.identifiers.org/articles/api.html#registry">identifiers.org 
registry API</a> if not found on the target page.  If you know of data records with 
good, machine-readable citation metadata in other formats, please 
<a href="mailto:$contact_email">let me know</a>. Formatting follows the Nature 
Research style. For more information on scholarly data citation standards please see 
<a href="https://doi.org/10.1038/sdata.2018.29">Wimalaratne et al.</a>, 
<a href="https://doi.org/10.1038/s41597-019-0031-8">Fenner et al.</a>, 
and <a href="https://doi.org/10.1038/sdata.2018.259">Cousijn et al.</a></p> 
<p style="text-align:left"><strong>Try these examples:</strong> <a href="$tool_url?DOI=&repoRF=pride.project&ACC=PXD001416&PROV=omicsdi">PXD001416 via OmicsDI</a>,
<a href="$tool_url?DOI=https%3A%2F%2Fdoi.org%2F10.14284%2F350&repoRF=&ACC=&PROV=">https://doi.org/10.14284/350</a> (DataCite), 
<a href="$tool_url?DOI=10.1575%2F1912%2Fbco-dmo.804502.1&repoRF=&ACC=&PROV="> https://doi.org/10.1575/1912/bco-dmo.804502.1</a> (Crossref or Schema.org), 
<a href="$tool_url?DOI=10.1594%2FPANGAEA.904761&prefer_schema=true&repoRF=&ACC=&PROV="> https://doi.org/10.1594/PANGAEA.904761</a> (DataCite or Schema.org),  
<a href="$tool_url?DOI=&repoRF=pdb&ACC=2gc4&PROV=pdbe"> 2gc4 via PDBe</a>.
</p> 
        
<p><strong>Note:</strong> this is a personal project, and not a service provided 
by <a href="https://www.nature.com/nature-research">Nature Research</a> or 
<em><a href="https://nature.com/sdata/">Scientific Data</a></em>.</p>
<p><strong>Latest updates</strong>: Caching! New dark theme. Also, schema.org & Crossref support.</p>

EOF

}

sub print_prompt {
    my %form_prefill;
    
    # force a print flush, so that user sees a more complete html page while waiting for work to finish
    $| = 1; 
    
    # Generate HTML snippets if form needs to be prefilled
    if ( $doi ) { $form_prefill{doi} = "value=\"$doi\""; } 
    else { $form_prefill{doi} = ''; }
    if ( $prefer_schema ) { $form_prefill{prefer_schema} = "checked=\"checked\""; }
    else { $form_prefill{prefer_schema} = ''; }
    if ( $repo ) { $form_prefill{repo} = "value=\"$repo\""; } 
    else { $form_prefill{repo} = ''; }
    if ( $acc ) { $form_prefill{acc} = "value=\"$acc\""; } 
    else { $form_prefill{acc} = ''; }
    if ( $prov ) { $form_prefill{prov} = "value=\"$prov\""; } 
    else { $form_prefill{prov} = ''; }
    
        
    # print the form    
    print <<EOF;

<form> 
<div class="row">
  <div class="column">
    <h4>Enter a dataset DOI</h4>
      <input type="text" name="DOI" $form_prefill{doi} size="30" maxlength="500">
      <input style="display:inline" type="checkbox" id="prefer_schema" name="prefer_schema" value="true" $form_prefill{prefer_schema}>
      <label for="prefer_schema"> Prefer Schema.org</label>
      <p>If box is checked, Schema.org metadata will be used when available instead of DataCite or Crossref.</p>
  </div> 
  
  <div class="column">
    <h4>Or, enter an identifiers.org prefix and accession ID</h4>
    <table>
      <tr><td>Prefix:</td><td><input type="text" name="repoRF" $form_prefill{repo} maxlength="500"></td></tr>
	  <tr><td>Accession:</td><td><input type="text" name="ACC" $form_prefill{acc} maxlength="500"></td></tr>
      <tr><td>Provider&nbsp;(optional):</td><td><input type="text" name="PROV" $form_prefill{prov} maxlength="500"></td></tr>
	</table>
	</br>See <a href="https://n2t.net/e/cdl_ebi_prefixes.yaml">here</a> for supported prefixes and providers</br>
	    
  </div>
</div>
<div class="button">
<input type="submit" value="Get data citation" style="font-size : 20px;">
</div>
</form>
	
EOF

    $| = 0;

}

sub make_results {
    my $citation = shift; 
    
    return <<EOF;
    
    <div class="results">
      <h3>Data citation information found via $source{name}:</h3>
      <p>$citation</p>
    </div>
    
EOF
}

sub make_details {
    
    my $warnings = '';
    
    foreach ( @warnings ) {
        $warnings .= "<p>WARNING: $_</p>\n";
    }
    
    return <<EOF;
    
    <div class="wrap-collabsible">
        <input id="collapsible" class="toggle" type="checkbox">
        <label for="collapsible" class="lbl-toggle">Details</label>
        <div class="collapsible-content">
          <div class="content-inner">
            <p>Metadata obtained from <a href="$source{url}">$source{url}</a></p>
            $warnings
            <p><pre>$source{metadata}</pre></p>
    </div></div></div>
EOF

}    