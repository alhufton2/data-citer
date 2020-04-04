# data-citer
A CGI application for generating well-formatted data citations

A version of this webtool is available live at: https://alhufton.com/cgi-bin/data-citer.cgi. The live version has a six hour cache. 

This webform attempts to construct a formatted data citation from a DOI or an identifiers.org registered accession number. Citation information is obtained from the DataCite or Crossref APIs, or, failing that, by trying to search the target page for Schema.org metadata. Only Schema.org metadata in JSON-LD is currently supported. For identifiers.org datasets, a repository name is obtained from the identifiers.org registry API if not found on the target page. 

The version hosted in GitHub is configured to run off the Apache server bundled with most Mac OS X systems. Just copy the script into your ~/Sites/ folder, change permissions to 755, install the necessary Perl modules, and then activate the Apache server (if needed). It should then run in a browser via the link: http://localhost/~user/data-citer.cgi. Running a local version may be useful if you want to test for changes in metadata sources, which could be masked by the cache on the public version.
