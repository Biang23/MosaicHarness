from __future__ import annotations

from mosaic_harness.platform.templates import TemplateCatalog, built_in_templates


def test_built_in_templates_are_discoverable_and_create_blueprints() -> None:
    catalog = TemplateCatalog(built_in_templates())

    templates = catalog.discover("research")
    blueprint = catalog.instantiate(
        "researcher",
        slug="my-researcher",
        model_ref="openai:test",
    )

    assert templates[0].id == "researcher"
    assert blueprint.slug == "my-researcher"
    assert blueprint.template_id == "researcher"
    assert "web_search" in blueprint.tool_refs


def test_template_catalog_rejects_unknown_template_and_duplicate_ids() -> None:
    catalog = TemplateCatalog(built_in_templates())

    try:
        catalog.instantiate("missing", slug="missing-agent", model_ref="openai:test")
    except KeyError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("unknown template should fail")
