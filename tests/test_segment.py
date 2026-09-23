"""Segmenter: every heading style a real lease turns up in."""

from lease_abstract.segment import by_category, categorise, family_text, segment


def _ids(clauses):
    return [c.id for c in clauses]


def test_numbered_dot_headings_with_subclauses():
    text = "1. PARTIES\n1.1 Landlord: A.\n1.2 Tenant: B.\n\n2. RENT\n2.1 R 100 per month."
    cl = segment(text)
    assert _ids(cl) == ["c1", "c1.1", "c1.2", "c2", "c2.1"]
    assert cl[0].heading == "PARTIES" and cl[0].category == "parties"
    assert cl[1].parent_id == "c1"
    assert cl[3].category == "rent" and cl[4].parent_id == "c2"


def test_top_level_sections_are_siblings_not_a_chain():
    """Section 3 must not become a descendant of section 2 (family text would swallow the lease)."""
    text = "1. PARTIES\n1.1 A.\n\n2. PREMISES\n2.1 B.\n\n3. DURATION\n3.1 C.\n\nSigned on 1 May 2026."
    cl = segment(text)
    by_id = {c.id: c for c in cl}
    assert by_id["c2"].parent_id is None
    assert by_id["c3"].parent_id is None
    assert "B." not in family_text(cl, "c1")
    assert family_text(cl, "c3") == "C."


def test_paren_numbering_style():
    text = "1) Parties\n1.1) Landlord: A.\n\n2) Rent\n2.1) R100 per month."
    cl = segment(text)
    assert _ids(cl) == ["c1", "c1.1", "c2", "c2.1"]
    assert cl[0].heading == "Parties"
    assert cl[3].category == "rent"


def test_lettered_items_hang_off_the_numbered_clause():
    text = "8. MAINTENANCE\n8.1 The Landlord is responsible for:\n(a) the roof;\n(b) the geyser.\n8.2 The Tenant is responsible for:\n(a) the garden."
    cl = segment(text)
    assert _ids(cl) == ["c8", "c8.1", "c8.1.a", "c8.1.b", "c8.2", "c8.2.a"]
    by_id = {c.id: c for c in cl}
    assert by_id["c8.1.b"].parent_id == "c8.1"  # (b) is a sibling of (a), not its child
    assert by_id["c8.2.a"].parent_id == "c8.2"
    assert all(c.category == "maintenance" for c in cl)


def test_all_caps_headings_without_numbers():
    text = "PARTIES\n\nThis agreement is between A and B.\n\nDEPOSIT\n\nThe Tenant shall pay a deposit of R100."
    cl = segment(text)
    assert _ids(cl) == ["s1", "s2"]
    assert cl[0].heading == "PARTIES" and cl[0].text.startswith("This agreement")
    assert cl[1].category == "deposit"


def test_unnumbered_paragraphs_get_p_ids_and_parent():
    text = "DEPOSIT\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    cl = segment(text)
    assert _ids(cl) == ["s1", "p1", "p2"]
    assert cl[1].parent_id == "s1" and cl[2].parent_id == "s1"


def test_title_line_is_categorised_title_and_children_are_not():
    text = "RESIDENTIAL LEASE AGREEMENT\n\n1. GENERAL\n1.1 Whole agreement."
    cl = segment(text)
    assert cl[0].category == "title"
    assert cl[1].parent_id == "s1"
    assert cl[1].category != "title"


def test_page_break_markers_bump_page_and_are_dropped():
    text = "1. PARTIES\n1.1 A.\n\f\n2. RENT\n2.1 B.\n--- Page 2 of 3 ---\n3. DEPOSIT\n3.1 C."
    cl = segment(text)
    pages = {c.id: c.page for c in cl}
    assert pages["c1"] == 1 and pages["c2"] == 2 and pages["c3"] == 3
    assert not any("Page" in c.text for c in cl)


def test_ids_are_stable_across_runs_and_unique_on_duplicates():
    text = "1. A\n1.1 x.\n1. A again\n1.1 y."
    a, b = segment(text), segment(text)
    assert _ids(a) == _ids(b)
    assert len(set(_ids(a))) == len(a)
    assert "c1-2" in _ids(a)


def test_categorise_uses_word_boundaries():
    assert categorise("TERMINATION AND NOTICE", "") == "notice"
    assert categorise("Term", "") == "term"
    assert categorise("RENTAL AND ESCALATION", "") == "rent"
    assert categorise(None, "The Tenant shall pay a deposit of R100.") == "deposit"
    assert categorise(None, "Nothing relevant here.") == "other"


def test_by_category_and_family_text_on_demo(demo_texts):
    cl = segment(demo_texts["01_compliant.txt"])
    assert by_category(cl, "deposit")[0].id == "c5"
    fam = family_text(cl, "c8")
    assert "structural repairs" in fam and "garden" in fam
    assert "deposit" not in fam.lower()
