# data-citer
A CGI application for generating well-formatted data citations

[A version of this webtool is available live here](https://alhufton.com/cgi-bin/data-citer.cgi)

[Read the associated blog](https://alhufton.com/building-data-citations-from-roadmap-compliant-metadata-sources/)

This webform attempts to construct a formatted data citation from a [DOI](https://www.doi.org/) or an [identifiers.org](https://identifiers.org/) registered accession number. Citation information is obtained from the [DataCite](https://datacite.org/) or [Crossref](https://www.crossref.org/) APIs, or, failing that, by trying to search the target page for [Schema.org](https://schema.org/) metadata. Only Schema.org metadata in JSON-LD is currently supported. For identifiers.org datasets, a repository name is obtained from the identifiers.org registry API if not found on the target page.

The live version has a six hour cache. If you want to test for changes in metadata sources more quickly, you may want to run the tool locally. The version hosted in GitHub is configured to run off the Apache server bundled with most Mac OS X systems. Just copy the script into your ~/Sites/ folder, change permissions to 755, install the necessary Perl modules, and then activate the Apache server (if needed). It should then run in a browser via the link: http://localhost/~user/data-citer.cgi. 

## citation styles
The current version supports four citation styles. Links to descriptions of the styles are provided below. 
* [Nature Research](https://www.nature.com/sdata/publish/submission-guidelines#refs)
* [Copernicus](https://www.atmospheric-chemistry-and-physics.net/submission.html#references)
* [APA](https://apastyle.apa.org/style-grammar-guidelines/references/examples/data-set-references) used by the AGU journals, among others
* [Vancouver/ICMJE](https://www.nlm.nih.gov/bsd/uniform_requirements.html#electronic) used by the PLOS journals, among others

## dependencies
* CGI::Carp
* CGI::Simple
* CHI 
* Encode
* LWP::UserAgent
* HTML::TokeParser::Simple
* Date::Parse::Lite
* JSON::MaybeXS
* Text::Names
