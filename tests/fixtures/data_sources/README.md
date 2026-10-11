# Structured-source fixtures

- `fmi_warnings_atom.xml` was captured from
  `https://alerts.fmi.fi/cap/feed/atom_fi-FI.xml` at 2026-10-10 22:42 UTC. It retains
  four real embedded Finnish CAP records from the 21:16:19 UTC update. Repetitive
  polygons and Swedish/English `info` blocks were removed to keep the fixture small.
- `fintraffic_messages.json` retains the real 2026-10-08 version 1 of situation
  `GUID50472054` (road 16 closed at Lapua) from Digitraffic history, plus real active
  situation `GUID50471971` (routine Turku road works) fetched from the task's v1 endpoint
  on 2026-10-10. Geometry and unused contact/location-code fields were removed.
- The two rights fixtures retain the exact live licence paragraphs fetched on
  2026-10-10 from the provider URLs pinned in `sources/finnish-official.json`.

All removals are structural fixture minimisation; retained source values are unchanged.
