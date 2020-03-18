#!/usr/bin/perlml
use strict;
use warnings;
use utf8;

use CGI::Simple;
my $q = CGI::Simple->new;
$q->charset('utf-8');      # set the charset

use Encode;
use LWP::UserAgent;
use JSON::PP; 
use HTML::HeadParser;
use Text::Names qw(parseName);
use open qw( :encoding(UTF-8) :std );

$CGI::Simple::POST_MAX=1024 * 100;  # max 100K posts
$CGI::Simple::DISABLE_UPLOADS = 1;  # no uploads

my $acc = $q->param('ACC'); 
my $repo = $q->param('repoRF');
my $doi = $q->param('DOI');
my $prov = $q->param('PROV');
my $cut = 5; # defines length at which author lists are truncated with et al. 
my $contact_email = "contact\@alhufton.com";

# Define core metadata fields to be filled
my ($title, $authors, $date, $year, $publisher, $id); 

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
	my $source_declare;

    # If user provided an accession number & repo prefix
    if ($acc && $repo) {
        my $data_url = &build_url_acc($acc, $repo, $prov);
        $id = $data_url; 
        #print "<p>Trying to obtain Dublincore metadata from <a href=\"$id\">$id</a></p>\n";
        ($title, $publisher, $date, $authors) = &get_dc_metadata( $data_url );
        &fail unless ($publisher && $date); 
        $source_declare = "DublinCore metadata";
        # the date parsing below is probably not robust 
        if ( $date =~ s/([0-9]+)[-:].*$// ) {
          $year = $1;
        } else {
          $year = $date;
        }
        
    # Or if a DOI was provided
    } elsif ( $doi ) {
            # clean & check for a valid DOI
            $doi =~ s/^doi:[\s]*//;
            $doi =~ s/^https*:\/\/doi\.org\///;
            $doi =~ s/^https*:\/\/dx\.doi\.org\///;
            $doi =~ s/\s+//g;
            unless ( $doi =~ /^10\./ ) { print "Invalid DOI provided: $doi.\n\n"; exit; }
            
            $id = "https://doi.org/$doi"; 
            ($title, $publisher, $date, $authors) = &get_datacite_metadata( $doi );
            $year = $date;
            &fail unless ($publisher && $date);
            $source_declare = 'DataCite';
            #clean the date field as needed?
    } else {
        return;
    }
        
    my $citation = &citation_nature();
    print "<div class=\"results\">\n";
    print "<h3>Data citation information found via $source_declare:</h3>\n";
    print "<p>$citation</p>\n\n" if $citation;
    print "</div>\n";
            
}

# Build a URL according to the rules defined in https://doi.org/10.1038/sdata.2018.29
sub build_url_acc {
    my $acc = shift;
    my $repo = shift;
    my $prov = shift;
    my $url;
    if ($prov) { $url = "http://identifiers.org/$prov/$repo:$acc" }
    else { $url = "http://identifiers.org/$repo:$acc"}
    print STDERR "url: $url\n";
    return $url;
}

# Get DataCite metadata from a provided DOI
sub get_datacite_metadata {
    my $datacite_doi = shift;
    my $ua = LWP::UserAgent->new;
    $ua->timeout(10);
   
    # Is this a DataCite DOI?
    my $response = $ua->get("https://api.crossref.org/works/$datacite_doi/agency");
    if ($response->is_success) {
        my $agency_check = decode_json $response->content;
        unless ( $agency_check->{message}->{agency}->{id} eq 'datacite' ) {
            print "\n\nProvided DOI is not registered with DataCite.\n\n"; exit;
        }
    } else {
        print $response->status_line; exit;
    }
    
    # Ok, get the DataCite metadata
    $response = $ua->get("https://data.datacite.org/application/vnd.datacite.datacite+json/$datacite_doi");
    if ($response->is_success) {
        #print $response->content;
        my $metadata = decode_json $response->content;
        my @authors; 
        foreach my $element ( @{$metadata->{creators}} ) {
            if ($element->{nameType} eq 'Personal') {
                $element->{name} =~ s/\(.*?\)//g;
                push @authors, &name_parser_punc($element->{name});
            } else {
                push @authors, $element->{name};
            }
        }
        return (
            $metadata->{titles}->[0]->{title},
            $metadata->{publisher},
            $metadata->{publicationYear},
            \@authors
            );
    } else {
        print $response->status_line; exit;
    }
}

# Get DublinCore metadata from the header of a target URL
sub get_dc_metadata {
    my $url = shift;
    
    my $ua = LWP::UserAgent->new;
    $ua->timeout(10);
    my $response = $ua->get($url);
    #print $response->as_string;
    
    if ($response->is_success) {
        my $metadata = HTML::HeadParser->new;
        $metadata->parse( decode_utf8 $response->content );
        my @authors; 
        foreach my $element ( $metadata->header( 'X-Meta-DC.creator' ) ) {
            push @authors, &name_parser_punc($element);
        }
        return (
            $metadata->header( 'X-Meta-DC.title' ),
            $metadata->header( 'X-Meta-DC.publisher' ),
            $metadata->header( 'X-Meta-DC.date' ),
            \@authors
            );
    } else {
        print "<p>Invalid URL: $url</br>" . $response->status_line . "</p>\n";
        &print_tail;
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
</style>
</head>
<body>
    
EOF

}

sub print_header {
    print "<div class=\"header\"><h1>Data Citation Formatter</h1></div>\n";
    print "<div class=\"intro\">\n";
    unless ($acc || $repo || $doi || $prov || $acc) {
        &print_intro;
    } else {
        print "<p>Search for citation information for another dataset.</p>\n";
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
through DataCite (for DOIs) and Dublin Core (for accession ids). Do you know of 
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
target webpage, and then the header of that page is searched for DublinCore 
metadata tags. The latter is poorly tested and not likely to work in most cases. 
If you know of identifiers.org data records with good, machine-readable citation 
metadata, please <a href="mailto:$contact_email">let me know</a>. Formatting follows
the Nature Research style. For more information on
scholarly data citation standards please see 
<a href="https://doi.org/10.1038/sdata.2018.29">Wimalaratne et al.</a>, 
<a href="https://doi.org/10.1038/s41597-019-0031-8">Fenner et al.</a>, 
and <a href="https://doi.org/10.1038/sdata.2018.259">Cousijn et al.</a></p> 
        
<p><strong>Note:</strong> this is a personal project, and not a service provided by <a href="https://www.nature.com/nature-research">Nature Research</a> or <em><a href="https://nature.com/sdata/">Scientific Data</a></em>.</p>
<p><strong>Latest updates</strong>: Improved named parsing, better error messages for accession number searches and some rudimentary styling.</p>

EOF

}

sub print_prompt {
    print <<EOF;

<form> 
<div class="row">
  <div class="column" style="background-color:#aaa;">
    <strong>Enter a dataset DOI</strong><br>
    <input type="text" name="DOI"><br>
    Dataset must be registered with <a href="https://datacite.org/">DataCite</a>
  </div> 
  <div class="column" style="background-color:#bbb;">
    <strong>Or, enter a repository prefix and a valid accession identifier.</strong></br>
	See <a href="https://n2t.net/e/cdl_ebi_prefixes.yaml">here</a> for supported prefixes and providers</br>
	Prefix:&nbsp;<input type="text" name="repoRF"></br>
	Accession:&nbsp;<input type="text" name="ACC"></br>
	Provider&nbsp;(optional):&nbsp;<input type="text" name="PROV">
  </div>
</div>
<div class="button"><input type="submit" value="Get data citation" style="font-size : 20px;"></div>
</form>
	
EOF

}