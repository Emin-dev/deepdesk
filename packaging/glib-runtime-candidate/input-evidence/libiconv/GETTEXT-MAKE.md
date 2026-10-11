# GNU Make gate: new declaration, pre-existing gettext PO requirement

The existing gettext-1.0.tar.gz was read as data only. Its exact SHA-256 was independently recomputed as `85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a` (32,694,085 bytes), matching the accepted source identity. No existing lane file was edited or executed.

- gettext-1.0/DEPENDENCIES:334–337 and libtextstyle/DEPENDENCIES:53–56 declare native make for in-tree builds or GNU Make >=3.79.1.
- But gettext-runtime/po/Makefile.in.in:15–24 explicitly requires the POSIX-2024 `!=` assignment operator, naming GNU Make >=4.0 and supported BSD makes. Lines 81, 83, 86, 92, 94, 96, 120 and 131 actually use it.
- libiconv 1.19 DEPENDENCIES explicitly raises its GNU Make requirement to 4.0; its po/Makefile.in.in contains the same requirement and constructs. Its ChangeLog links the update to using gettext 1.0's PO machinery.

Therefore the Make>=4 issue is already latent in the accepted gettext runtime PO path; it is not unique to adding libiconv. gettext's top-level dependency prose is insufficient to approve an older Make for that path. Configure-only success, or reaching earlier libtextstyle compilation, cannot establish a later PO build passes.

The two PO makefiles are not byte-identical. Exact inspected hashes:
- gettext-runtime/po/Makefile.in.in: `836f5377869d055cff4c1995c3ed93421fa1eada1108d0961a9933ca1764edbe`
- libiconv 1.19 po/Makefile.in.in: `57578892f3f9d93708357c65c66a7929b9073e52aeef061e4142ec9f0ef6eb2a`

Inspected gettext members and their archive identities are retained under ../evidence/gettext-comparison/. This report has not queried the runner's Make, acquired a newer Make, removed PO recursion, or disabled NLS. Future execution must bind a reviewed capable Make or stop.
