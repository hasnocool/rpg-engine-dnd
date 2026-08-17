# SRD content boundary

The engine core is ruleset-neutral. `srd.py` is an opt-in compatibility layer that records SRD provenance/licensing metadata and exposes structured mechanical helpers without copying sourcebook or SRD prose into the repository.

Content packs that include third-party rules text or data are responsible for carrying their own attribution, provenance and license metadata. The executable rule graph format itself is original engine infrastructure and deliberately accepts bounded structured operations rather than arbitrary script code.
