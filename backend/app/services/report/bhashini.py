"""STUB — Bengali translation and text-to-speech via Bhashini. NOT IMPLEMENTED.

This is the hook point, deliberately left empty for the MVP. Nothing imports it
and nothing calls it; it exists so that adding Bengali later is a matter of
filling in two functions rather than restructuring the report pipeline.

Why it plugs in here and not elsewhere: `report_writer.write()` produces
`sections` — six named slots of finished English prose. Translation is a
transformation of that dict, after the numbers are already fixed and before
`pdf_builder.build_pdf()` lays it out. So the whole feature is:

    sections = report_writer.write(facts)["sections"]
    sections_bn = bhashini.translate_sections(sections, target="bn")
    pdf = pdf_builder.build_pdf(facts, sections_bn)      # needs a Bengali font
    audio = bhashini.synthesise(sections_bn["headline"], target="bn")

Two things to know before implementing:

  - ReportLab has no Bengali glyphs by default. A Unicode Bengali font (Noto Sans
    Bengali) must be registered with `pdfmetrics.registerFont` and selected in
    `pdf_builder._styles()`, or the PDF will render empty boxes.
  - Numbers must not go through translation. They are already correct in `facts`
    and the PDF prints them from there; only the prose slots are translated.

Bhashini (https://bhashini.gov.in/) ULCA pipeline endpoints, for whoever picks
this up: `/ulca/apis/v0/model/getModelsPipeline` to resolve a pipeline, then the
returned inference endpoint for translation and TTS. Needs a ULCA API key and
user ID, which would become BHASHINI_API_KEY / BHASHINI_USER_ID in settings.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("bn",)  # Bengali — the language EKW officers and residents use


class BhashiniNotImplemented(NotImplementedError):
    """Raised by every function in this module. Bengali output is a stretch goal."""


def translate_sections(sections: dict[str, str], target: str = "bn") -> dict[str, str]:
    """Translate the report's prose slots. Not implemented — see module docstring."""
    raise BhashiniNotImplemented(
        "Bengali report translation is not implemented in the MVP. "
        "See the module docstring for where it plugs in."
    )


def synthesise(text: str, target: str = "bn") -> bytes:
    """Text-to-speech for a report headline. Not implemented — see module docstring."""
    raise BhashiniNotImplemented(
        "Bengali text-to-speech is not implemented in the MVP. "
        "See the module docstring for where it plugs in."
    )
