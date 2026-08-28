# Source legal texts

Everything the notice drafter is allowed to cite lives in this folder. The rule
the whole feature is built around:

> **Every regulatory claim must be retrieved and quoted with a section citation —
> never generated from the model's memory.** If retrieval finds nothing relevant,
> the API returns `grounded: false` and no notice is drafted.

So: nothing goes in here that isn't the real, verbatim text of a real instrument.
An approximate or model-reconstructed statute in this folder would defeat the
entire feature, because the drafter trusts what it retrieves.

## Present

| File | Document | Provenance |
|---|---|---|
| `wetlands_rules_2017.txt` | Wetlands (Conservation and Management) Rules, 2017 | Gazette of India Extraordinary, Part II §3(i), G.S.R. 1203(E), 26 Sep 2017. Extracted verbatim from <https://tnswa.tn.gov.in/pdf/wetlands%20rules.pdf>; page furniture stripped, no wording altered. |

The provision this project turns on is **Rule 4(2)(i)** — *"conversion for
non-wetland uses including encroachment of any kind"* is prohibited within
wetlands — read with **Rule 3(a)**, which applies the Rules to Ramsar sites, and
the East Kolkata Wetlands are Ramsar site no. 1208.

## Missing — add before relying on the notice output

**The 1992 Calcutta High Court order** in *People United for Better Living in
Calcutta (PUBLIC) v. State of West Bengal*, reported at **AIR 1993 Cal 215**,
which held that an obligation is cast on the Government of West Bengal not to
change the nature and character of the land in the East Kolkata Wetlands.

It is deliberately **not** included, because no verbatim copy could be sourced
at build time and a paraphrase would be worse than an absence. To add it:

1. Obtain the full text — Indian Kanoon, SCC Online, Manupatra, or a certified
   copy from the Calcutta High Court registry.
2. Save it here as `public_v_west_bengal_1993.txt` with this header:

   ```
   # DOCUMENT: People United for Better Living in Calcutta (PUBLIC) v. State of West Bengal, AIR 1993 Cal 215
   # SOURCE: <where you got it>
   ```

3. Rebuild the index:

   ```bash
   cd backend && python -m app.rag.ingest --show "encroachment of wetland"
   ```

Until then the notice drafter cites the 2017 Rules only, and says so.

## Adding any other instrument

Same shape: plain `.txt` or `.md`, a `# DOCUMENT:` header, verbatim body.
`ingest.py` splits on numbered provisions (`4.`, `4(2)`, `(i)`, `Rule 4`,
`Section 12`) and keeps each one as a separately citable chunk.
