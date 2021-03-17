#!/Users/alhufton/perl5/perlbrew/perls/perl-5.32.1/bin/perl

# use the shebang line below when running at bluehost
#   !/usr/bin/perlml

###########################
# Data Citation Formatter #
###########################
# Written by Andrew L Hufton (contact@alhufton.com)
# See https://github.com/alhufton2/data-citer for updates
#
# A webtool for creating well-formatted data citations, following the data 
# citation roadmap guidelines. See the blog at the link below for details:
# https://alhufton.com/building-data-citations-from-roadmap-compliant-metadata-sources/
#
##### Before running ######
# 1. enter your $contact_email, to identify yourself to the CrossRef and DataCite APIs
# 2. Configure the cache as needed for your system. See CHI documentation for details. 
# 3. Check that the shebang line points at the right perl installation for your system
###########################

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
$q->no_cache(1);

# Load other packages
use CHI; 
use Encode;
use LWP::UserAgent;
use Text::Names qw(parseName);
use HTML::TokeParser::Simple;
use Date::Parse::Lite;
use JSON::MaybeXS;
use open qw( :encoding(UTF-8) :std );

# Read in any CGI parameters and clean whitespace
my $tool_url = $q->url();
my $doi  = $q->param('DOI');
$doi =~ s/\s+//g if $doi;
my $acc  = $q->param('ACC');
$acc =~ s/\s+//g if $acc;
my $repo = $q->param('REPO');
my $prov = $q->param('PROV');
my $prefer_schema = $q->param('prefer_schema');

# Open the cache
my $cache = CHI->new( driver => 'File' );
# my $cache = CHI->new( driver => 'File', root_dir => '/home3/alhufton/tmp/data-citer' );

# Set various variables
my $year = "????"; # defines default text for 'year' field
my $contact_email = 'enter email address';
my $timeout = 30;
my $cache_time = '30';
my $cache_time_registry = '1 month';
my $json = JSON::MaybeXS->new->pretty;  # creates a json parsing object

# Create the web useragent
my $ua = LWP::UserAgent->new;
$ua->timeout($timeout);
$ua->agent('Mozilla/5.0');

# Define core metadata fields to be filled
my ($title, $date, $publisher, $id, $version);
my %source; # has fields url, metadata and name
my @authors;
my @warnings;

binmode(STDOUT, ":utf8");

# Main body 
print $q->header();
start_html();
print_header();
print_prompt();
do_work();
print_tail();

exit;

sub do_work {
    my $cache_id;
    my %registry;

    # Build the ID
    if ( $acc && $repo ) {
    	%registry = getRegistry();
    	my $prefix = $registry{$repo}->{prefix};
         
        if ($prov) { $id = "https://identifiers.org/$prov/$prefix:$acc" }
        else { $id = "https://identifiers.org/$prefix:$acc"}
        $cache_id = $id; 

    } elsif ( $doi ) {
        
        # clean & check for a valid DOI
        $doi =~ s/^doi:[\s]*//;
        $doi =~ s/^https*:\/\/(dx\.)*doi\.org\///;
        unless ( $doi =~ /^10\./ ) { print "Invalid DOI provided: $doi.\n\n"; &print_tail(); exit; }
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
                
        # Assign publisher name from identifiers.org registry if it was not in the HTML
        unless ($publisher) {
        	if ($prov) {
        		$publisher = $registry{$repo}->{providerCode}->{$prov};
        	} else {
        		$publisher = $repo;
        	}
        	unless ($source{name}) { $source{name} = 'identifiers.org API'; }
        	else { $source{name} .= ' & identifiers.org API'; }
        }

    } elsif ( $doi ) {
        # Try DataCite or Crossref, with fall back to target HTML
        if ( $prefer_schema ) { &get_html_metadata( $id ); }
        unless ( $publisher ) { &get_doi_metadata(); }
    }

    &fail unless ($publisher && $id && $year);
    
    # Build the results
    my $results = &make_results();

    if ( $repo && $registry{$repo}->{providerCode} ) {
    	$results .= &makeAltProv($registry{$repo}->{providerCode}); 
    }
    $results .= &make_details() if $source{metadata};
    
    print $results;
    $cache->set($cache_id, $results, $cache_time);
}

sub makeAltProv {
    my %provs = %{$_[0]};
    my $html = "<div class=\"results\"><h3>Other providers</h3><p>";
    foreach my $provider ( keys %provs ) {
        my $repo_url = $q->url_encode( $repo );
        $html .= "<a href=\"$tool_url?DOI=&REPO=$repo_url&ACC=$acc&PROV=$provider\" class=\"provider\">$provider</a>\n";
    }
    $html .= "</p></div>\n";
    return $html;
}
   
# Get metadata from a provided DOI
sub get_doi_metadata {

    my $agency;
   
    # Get DOI agency
    my $response = $ua->get("https://api.crossref.org/works/$doi/agency");
    if ($response->is_success) {
        my $agency_message = $json->decode($response->content);
        $agency = $agency_message->{message}->{agency}->{id};
    } else {
        print $response->status_line; &fail();
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
            if ( $metadata->{creators} ) {
                foreach my $element ( @{$metadata->{creators}} ) {
                    push @authors, &parse_author( { 
                            'name' => $element->{name}, 
                            'type' => $element->{nameType}, 
                            'familyName' => $element->{familyName} ,
                            'givenName' => $element->{givenName}
                    } );
                }
            }
    
            $publisher       = $metadata->{publisher} if ( $metadata->{publisher} );
            $version         = $metadata->{version} if ( $metadata->{version} );
            $title           = &assign2($metadata, 'titles', 'title'); 
            $year            = $metadata->{publicationYear} if ( $metadata->{publicationYear} );
            $source{name}     = 'DataCite';
            $source{metadata} = $json->encode($metadata);
        } else {
            print $response->status_line; &fail();
        }
    } elsif ( $agency eq 'crossref' ) {
        
        # Get Crossref metadata
        $source{url} = "https://api.crossref.org/works/$doi";
        $response = $ua->get($source{url});
        if ($response->is_success) {
    
            my $metadata = decode_json $response->content;
            unless ( $metadata->{message}->{type} eq 'dataset' ) {
                print "<p>Error: Digital object is not registered at Crossref as a dataset ($metadata->{message}->{type}).</p>";
                &print_tail(); exit;
            }
            
            if ( $metadata->{message}->{author} ) {
                foreach my $element ( @{$metadata->{message}->{author}} ) {
                    push @authors, &parse_author( { 
                            'name' => $element->{name},
                            'familyName' => $element->{family},
                            'givenName' => $element->{given}
                    } );
                }
            }
    
            $publisher       = $metadata->{message}->{publisher} if ( $metadata->{message}->{publisher} ); 
            $title           = $metadata->{message}->{title}->[0] if ( $metadata->{message}->{title}->[0] ); 
            $version         = $metadata->{message}->{version} if ( $metadata->{message}->{version} );
            if ( $metadata->{message}->{issued}->{'date-parts'}->[0]->[0] ) {
                $year        = $metadata->{message}->{issued}->{'date-parts'}->[0]->[0];
            } elsif ( $metadata->{message}->{indexed}->{'date-parts'}->[0]->[0] ) {
                $year        = $metadata->{message}->{indexed}->{'date-parts'}->[0]->[0];
            }
            $source{name}     = 'Crossref';
            $source{metadata} = $json->encode($metadata);
        } else {
            print $response->status_line; &fail();
        }
    }
  
}

# Get Schema.org metadata from a target URL
sub get_html_metadata {
    my $url = shift;
    
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

# Author parsing subroutine
sub parse_author {
    my $author_info = shift; #hash reference
    die "bad author info provided to parse_author.\n" unless ( $author_info->{familyName} || $author_info->{givenName} || $author_info->{name} );
    
    if ( lc $author_info->{type} eq 'person' || lc $author_info->{type} eq 'personal' || $author_info->{familyName} || $author_info->{givenName} ) {
        if ( $author_info->{familyName} || $author_info->{givenName} ) {
            if ( $author_info->{familyName} && $author_info->{givenName} ) {
            	return &name_parser_punc("$author_info->{familyName}, $author_info->{givenName}");
            } elsif ( $author_info->{name} ) {
            	return &name_parser_punc($author_info->{name});
            } elsif ( $author_info->{familyName} ) {
                push @warnings, "Author information included a family name '$author_info->{familyName}' without a given name.";
                return $author_info->{familyName};
            } elsif ( $author_info->{givenName} ) {
                push @warnings, "Author information included a given name '$author_info->{givenName}' without a family name.";
                return $author_info->{givenName};
            }
        } else {
            return &name_parser_punc($author_info->{name});
        }
    } else {
    	# Check if it feels like a well-formatted name
    	if ( $author_info->{name} =~ /^[A-Z][\p{L}]+,/ ) {
    		return &name_parser_punc($author_info->{name});
    	} else {
    		return $author_info->{name};
    	}		
    }
}

# Formats names as lastname, initials with full punctuation. 
sub name_parser_punc {
    my $input = shift;
    $input =~ s/\(.*?\)//g; # remove anything in parentheses (necessary due to some pathological DataCite examples)
    
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
    unless ( $publisher ) { $publisher = &assign2( $metadata, 'publisher', 'legalName' ); }
    $date      = &assign( $metadata, 'datePublished' );
    $version   = &assign( $metadata, 'version' );
    
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
            push @authors, &parse_author( { 
                    'name' => $element->{name},
                    'familyName' => $element->{familyName},
                    'givenName' => $element->{givenName},
                    'type' => $element->{'@type'}
                } );
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
    
	my $cut = 5;       # defines length at which author lists are truncated with et al. 
    my $citation;
    
    my $author_line = "";
 
    if ( @authors ) {
        my $k = @authors; 
        if ($k > 0 ) {
            if ($k >= $cut) {
                $author_line = $authors[0] . " <em>et al.</em>"
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
    if ( $title ) {
        $title =~ s/\.$//; 
        $citation .= "$title. ";
    }
    $citation .= "<em>$publisher</em> " if $publisher;
    $citation .= "<a href=\"$id\">$id</a> " if $id;
    $citation .= "($year).";
    return $citation;
}

# Format a citation string according to the APA style (used by AGU) -- unfinished, still mostly nature
sub citation_apa {
    
	my $cut = 21;    # If 21 or more, show first 19, then '...', then last author
    my $citation;
    
    my $parenthetical_details = '';
    if ($acc && $version) {
    	$parenthetical_details = "($acc; Version $version)";
    } elsif ($acc) {
    	$parenthetical_details = "($acc)";
    } elsif ($version) {
    	$parenthetical_details = "(Version $version)";
    }
    
    my $author_line = "";
 
    if ( @authors ) {
        my $k = @authors; 
        if ($k > 0 ) {

			my $i = 0;
			my $connect = ", ";
			foreach my $author ( @authors ) {
				++$i; 
				if ($i == $k - 1) { $connect = ", & "; }
				if ($i == $k) { $connect = ""; }
				if ($i == $cut - 1 && $k > $cut ) { $author_line .= $author . ", . . . " . pop @authors; last; }
				$author_line .= $author . $connect;
			}
            $author_line .= "." unless ( $author_line =~ /\.$/ );
                
            $citation = "$author_line ";
        }
		$citation .= "($year). ";
		if ( $title ) {
			$title =~ s/\.$//; 
			$citation .= "<em>$title</em> $parenthetical_details [dataset]. ";
		}
	} elsif ( $title ) {
		$title =~ s/\.$//; 
		$citation = "<em>$title</em> $parenthetical_details [dataset]. ";
		$citation .= "($year). ";
	} else {
		$parenthetical_details =~ s/^\(|\)$//g;
		$citation = "$parenthetical_details [dataset]. ";
		$citation .= "($year). ";
	}
		
    # Ideally, now enter numerical identifiers and version numbers in parentheses
    $citation .= "$publisher. " if $publisher;
    $citation .= "<a href=\"$id\">$id</a> " if $id;
    
    return $citation;
}

# Format a citation string according to the Vancouver style
sub citation_vancouver {
    
	my $cut = 6;  
    my $citation;
  
    my @date = localtime();
    my @months = qw( Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec );
    my $current_year = $date[5] + 1900;
    my $current_date = "$date[3] $months[$date[4]] $current_year";
    
    my $author_line = "";
 
    if ( @authors ) {
        my $k = @authors; 
        if ($k > 0 ) {

			my $i = 0;
			my $connect = ", ";
			foreach my $author ( @authors ) {
				if ( $author =~ /^[A-Z][\p{L}]+,/ ) {
					$author =~ s/\.\s*|\,//g;
				}
				
				++$i; 
				if ($i == $k) { $connect = ""; }
				if ($i == $cut && $k > $cut ) { $author_line .= $author . ", et al."; last; }
				$author_line .= $author . $connect;
			}
			$author_line .= "." unless ( $author_line =~ /\.$/ );
                
			$citation = "$author_line ";
        }
    }
    if ( $title ) {
        $title =~ s/\.$//; 
        $citation .= "$title ";
    }
    $citation .= "[dataset]. ";
    $citation .= "Version $version. " if $version;
    $citation .= "$year [cited $current_date]. ";
    $citation .= "$publisher. " if $publisher;
    $citation .= "Available from: <a href=\"$id\">$id</a> " if $id;
    return $citation;
}

# Format a citation string according to the Copernicus style
sub citation_copernicus {
    
	my $cut = 100;       # defines length at which author lists are truncated with et al. 
    my $citation;
    
    my $author_line = "";
 
    if ( @authors ) {
        my $k = @authors; 
        if ($k > 0 ) {

			my $i = 0;
			my $connect = ", ";
			foreach my $author ( @authors ) {
				++$i; 
				if ($i == $k - 1) { $connect = ", and "; }
				if ($i == $k) { $connect = ""; }
				if ($i == $cut - 1 && $k > $cut ) { $author_line .= $author . ", et al."; last; }
				$author_line .= $author . $connect;
			}
			$author_line .= ":";
                
            $citation = "$author_line ";
        }
    }
    if ( $title ) {
        $title =~ s/\.$//; 
        $citation .= "$title, ";
    }
    $citation .= "$publisher [dataset], " if $publisher;
    $citation .= "<a href=\"$id\">$id</a>, " if $id;
    $citation .= "$year.";
    return $citation;
}

sub getRegistry {
	
	my $cache_results = $cache->get('IDENTIFIERS-ORG-REGISTRY');
    if ( defined $cache_results ) {
    	return %{$cache_results};
    }
	
    my %registry;

	my $response = $ua->get("https://registry.api.identifiers.org/resolutionApi/getResolverDataset");
    if ($response->is_success) {
    	my $registry = decode_json $response->content;
    	foreach my $element ( @{$registry->{payload}->{namespaces}} ) {
    		if ( defined $element->{prefix} ) {
    			$registry{ $element->{name} }->{prefix} = $element->{prefix};
				foreach my $resource ( @{$element->{resources}} ) {
					if ( defined $resource->{providerCode} && $resource->{providerCode} ne 'CURATOR_REVIEW' ) {
						$registry{ $element->{name} }->{providerCode}->{ $resource->{providerCode} } = $resource->{name};
					}
				}
			}
    	}
    	$cache->set('IDENTIFIERS-ORG-REGISTRY', \%registry, $cache_time_registry);
    	return %registry;
    } else {
    	die "Failed to download identifiers.org registry";
    }
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
<link rel="stylesheet" href="../css/tool.css?awear">
</head>
<body>
    
EOF

}

sub print_header {
    print <<EOF;
<div class="header">
  <h1><a href="$tool_url">{data citation formatter}</a></h1>
  <h4>Construct a formatted data citation from a <a href="https://www.doi.org/">DOI</a> or an <a href="identifiers.org/">identifiers.org</a> accession number</h4>
</div>
EOF
    print_menu();
    unless (($acc && $repo) || $doi ) {
        &print_intro;
    } 

}

sub print_tail {
    print <<EOF;
    
<div>&nbsp;</div>    
<div class="footer">
<p><a href="https://alhufton.com/">Home</a> 
| <a href="mailto:$contact_email">Contact</a> 
| <a href="https://github.com/alhufton2/data-citer">GitHub</a></p>
<p>© 2020 Andrew Lee Hufton</p>
<p><a href="https://alhufton.com/privacy-policy/">Privacy policy</a></p>
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
<div class="intro">
<a href="https://alhufton.com/building-data-citations-from-roadmap-compliant-metadata-sources/">Read the associated blog&nbsp;&#9656;</a>&nbsp;&nbsp;&nbsp;
<a href="https://github.com/alhufton2/data-citer">Source code and methods&nbsp;&#9656;</a> 
<p style="text-align:left"><strong>Try these examples:</strong> <a href="$tool_url?DOI=&REPO=PRIDE+Project&ACC=PXD001416&PROV=omicsdi">PXD001416 via OmicsDI</a>,
<a href="$tool_url?DOI=https%3A%2F%2Fdoi.org%2F10.14284%2F350&REPO=&ACC=">https://doi.org/10.14284/350</a> (DataCite), 
<a href="$tool_url?DOI=10.1575%2F1912%2Fbco-dmo.804502.1&REPO=&ACC="> https://doi.org/10.1575/1912/bco-dmo.804502.1</a> (Crossref or Schema.org), 
<a href="$tool_url?DOI=10.1594%2FPANGAEA.904761&prefer_schema=true&REPO=&ACC="> https://doi.org/10.1594/PANGAEA.904761</a> (DataCite or Schema.org),  
<a href="$tool_url?DOI=&REPO=Protein+Data+Bank&ACC=2gc4&PROV=pdbe"> 2gc4 via PDBe</a>.</p>
</div>

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
    
    # Get prefixes from identifiers.org, name has prefix and optionally provider
    my %registry = getRegistry(); # fill from cache or subroutine, move code below into subroutine and expand to capture providers
 
    my $repo_list;
    foreach (keys %registry) {
    	$repo_list .= "\"$_\", ";
    }
    $repo_list =~ s/, $//;
      
    # print the form    
    print <<EOF;

<form>
<div class="row">
  <div class="column">
    <h4>Enter a dataset DOI</h4>
      <input type="text" name="DOI" $form_prefill{doi} size="30" maxlength="500">
      <nobr><input style="display:inline" type="checkbox" id="prefer_schema" name="prefer_schema" value="true" $form_prefill{prefer_schema}>
      <label for="prefer_schema">Prefer&nbsp;Schema.org</label></nobr>
      <p>If box is checked, Schema.org metadata will be used when available instead of DataCite or Crossref.</p>
  </div> 
  
  <div class="column">
    <h4>Or, enter an identifiers.org repository and accession</h4>
    <table>
      <tr><td>Repository:</td><td><div class="autocomplete"><input autocomplete="off" size="25" id="myRepos" type="text" name="REPO" $form_prefill{repo}></div></td></tr>
	  <tr><td>Accession:</td><td><input type="text" size="25" name="ACC" $form_prefill{acc} maxlength="500"></td></tr>
	</table>	    
  </div>
</div>

<div class="button">
	<input type="submit" value="Get data citation" style="font-size: 20px;">
</div>
</form>

<script>
function autocomplete(inp, arr) {
  /*the autocomplete function takes two arguments,
  the text field element and an array of possible autocompleted values:*/
  var currentFocus;
  /*execute a function when someone writes in the text field:*/
  inp.addEventListener("input", function(e) {
      var a, b, i, val = this.value;
      /*close any already open lists of autocompleted values*/
      closeAllLists();
      if (!val) { return false;}
      currentFocus = -1;
      /*create a DIV element that will contain the items (values):*/
      a = document.createElement("DIV");
      a.setAttribute("id", this.id + "autocomplete-list");
      a.setAttribute("class", "autocomplete-items");
      /*append the DIV element as a child of the autocomplete container:*/
      this.parentNode.appendChild(a);
      /*for each item in the array...*/
      for (i = 0; i < arr.length; i++) {
        /*check if the item starts with the same letters as the text field value:*/
        if (arr[i].substr(0, val.length).toUpperCase() == val.toUpperCase()) {
          /*create a DIV element for each matching element:*/
          b = document.createElement("DIV");
          /*make the matching letters bold:*/
          b.innerHTML = "<strong>" + arr[i].substr(0, val.length) + "</strong>";
          b.innerHTML += arr[i].substr(val.length);
          /*insert a input field that will hold the current array item's value:*/
          b.innerHTML += "<input type='hidden' value='" + arr[i] + "'>";
          /*execute a function when someone clicks on the item value (DIV element):*/
          b.addEventListener("click", function(e) {
              /*insert the value for the autocomplete text field:*/
              inp.value = this.getElementsByTagName("input")[0].value;
              /*close the list of autocompleted values,
              (or any other open lists of autocompleted values:*/
              closeAllLists();
          });
          a.appendChild(b);
        }
      }
  });
  /*execute a function presses a key on the keyboard:*/
  inp.addEventListener("keydown", function(e) {
      var x = document.getElementById(this.id + "autocomplete-list");
      if (x) x = x.getElementsByTagName("div");
      if (e.keyCode == 40) {
        /*If the arrow DOWN key is pressed,
        increase the currentFocus variable:*/
        currentFocus++;
        /*and and make the current item more visible:*/
        addActive(x);
      } else if (e.keyCode == 38) { //up
        /*If the arrow UP key is pressed,
        decrease the currentFocus variable:*/
        currentFocus--;
        /*and and make the current item more visible:*/
        addActive(x);
      } else if (e.keyCode == 13) {
        /*If the ENTER key is pressed, prevent the form from being submitted,*/
        e.preventDefault();
        if (currentFocus > -1) {
          /*and simulate a click on the "active" item:*/
          if (x) x[currentFocus].click();
        }
      }
  });
  function addActive(x) {
    /*a function to classify an item as "active":*/
    if (!x) return false;
    /*start by removing the "active" class on all items:*/
    removeActive(x);
    if (currentFocus >= x.length) currentFocus = 0;
    if (currentFocus < 0) currentFocus = (x.length - 1);
    /*add class "autocomplete-active":*/
    x[currentFocus].classList.add("autocomplete-active");
  }
  function removeActive(x) {
    /*a function to remove the "active" class from all autocomplete items:*/
    for (var i = 0; i < x.length; i++) {
      x[i].classList.remove("autocomplete-active");
    }
  }
  function closeAllLists(elmnt) {
    /*close all autocomplete lists in the document,
    except the one passed as an argument:*/
    var x = document.getElementsByClassName("autocomplete-items");
    for (var i = 0; i < x.length; i++) {
      if (elmnt != x[i] && elmnt != inp) {
        x[i].parentNode.removeChild(x[i]);
      }
    }
  }
  /*execute a function when someone clicks in the document:*/
  document.addEventListener("click", function (e) {
      closeAllLists(e.target);
  });
}

/*An array containing all the repo names:*/
var repositories = [$repo_list];

/*initiate the autocomplete function on the "myRepos" element, and pass along the repo array as possible autocomplete values:*/
autocomplete(document.getElementById("myRepos"), repositories);
</script>
	
EOF

    $| = 0;

}

sub make_results {
    
    my $results = <<EOF;
    
<div class="results">
  <h3>Data citation information found via $source{name}:</h3>
	<div class="tab">
		<button class="tablinks" onclick="openCitation(event, 'nature')" id="defaultOpen">Nature Research</button>
		<button class="tablinks" onclick="openCitation(event, 'copernicus')">Copernicus</button>
		<button class="tablinks" onclick="openCitation(event, 'apa')">APA</button>
		<button class="tablinks" onclick="openCitation(event, 'vancouver')">Vancouver</button>
	</div>
      
EOF

    my $citation = &citation_nature();
    $results .= "<div id=\"nature\" class=\"tabcontent\"><p>$citation</p></div>\n";
    $citation = &citation_copernicus();
    $results .= "<div id=\"copernicus\" class=\"tabcontent\"><p>$citation</p></div>\n";
    $citation = &citation_apa();
    $results .= "<div id=\"apa\" class=\"tabcontent\"><p>$citation</p></div>\n";
    $citation = &citation_vancouver();
    $results .= "<div id=\"vancouver\" class=\"tabcontent\"><p>$citation</p></div>\n";
    
    $results .= <<EOF;
    
</div>
    
<script>
function openCitation(evt, styleName) {
  // Declare all variables
  var i, tabcontent, tablinks;

  // Get all elements with class="tabcontent" and hide them
  tabcontent = document.getElementsByClassName("tabcontent");
  for (i = 0; i < tabcontent.length; i++) {
	tabcontent[i].style.display = "none";
  }

  // Get all elements with class="tablinks" and remove the class "active"
  tablinks = document.getElementsByClassName("tablinks");
  for (i = 0; i < tablinks.length; i++) {
	tablinks[i].className = tablinks[i].className.replace(" active", "");
  }

  // Show the current tab, and add an "active" class to the button that opened the tab
  document.getElementById(styleName).style.display = "block";
  evt.currentTarget.className += " active";

}
  
// Get the element with id="defaultOpen" and click on it
document.getElementById("defaultOpen").click();
</script>

EOF

    return $results;
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

sub print_menu {
    print <<EOF;
<div class="nav"><p><a href="https://alhufton.com">home</a> &#9657; <a href="https://alhufton.com/tools/">tools</a> &#9657; data citation formatter</p></div>
EOF
}