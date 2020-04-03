# data-citer
A CGI application for generating well-formatted data citations

A version of this webtool is available live at: https://alhufton.com/cgi-bin/data-citer.cgi

This webform attempts to construct a formatted data citation from a DOI or an identifiers.org registered accession number. Citation information is obtained from the DataCite or Crossref APIs, or, failing that, by trying to search the target page for Schema.org metadata. Only Schema.org metadata in JSON-LD is currently supported. For identifiers.org datasets, a repository name is obtained from the identifiers.org registry API if not found on the target page. 

The live version has a six hour cache. 
