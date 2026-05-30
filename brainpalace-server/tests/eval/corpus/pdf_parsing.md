# PDF parsing and page handling

PDF documents are parsed page by page. Each page becomes one or more chunks.
Because every page shares the same source file path, chunk identifiers mix in
a per-page `page_label` so that chunks from different pages never collide in
storage.

Large multi-page PDFs (hundreds of pages) are streamed rather than loaded
whole, keeping memory bounded during indexing.
