from __future__ import annotations

from app.chunking import split_transcript
from app.merge import merge_extracts
from app.pipeline import assert_corpus, load_transcripts
from app.schemas import Decision, ExtractedRequirement, FeasibilityItem, ProposalDocument, ProposalSection, Requirement
from app.validate import check_proposal, locate_quote, quote_in_text


def run_selfcheck() -> None:
    transcripts = load_transcripts()
    assert_corpus(transcripts)
    meeting_a = next(item for item in transcripts if item.meeting_id == "mtg-a-search-mobile")
    sections = split_transcript(meeting_a)
    if len(sections) < 2:
        raise RuntimeError("Meeting A should split into overlapping sections")
    covered = set()
    for section in sections:
        covered.update(range(section.turn_start, section.turn_end))
        if section.turn_end - section.turn_start > 10:
            raise RuntimeError("section window exceeded")
    if covered != set(range(len(meeting_a.turns))):
        raise RuntimeError("sections do not cover the original transcript")
    overlap = set(range(sections[0].turn_start, sections[0].turn_end)) & set(
        range(sections[1].turn_start, sections[1].turn_end)
    )
    if not overlap:
        raise RuntimeError("adjacent sections do not overlap")
    quote = meeting_a.turns[5].text
    if not quote_in_text(quote, sections[0].text):
        raise RuntimeError("section text dropped a source turn")
    if locate_quote(meeting_a, "this sentence was never said by anyone") is not None:
        raise RuntimeError("quote matcher accepted text that is not in the source")

    base = dict(
        meeting_id="mtg-a-search-mobile",
        meeting_date="2026-10-18",
        section_index=0,
        topic_key="search_map",
        acceptance_criteria=[],
        dependencies=[],
        supersedes=False,
        priority="high",
        explicitness="explicit",
    )
    left = ExtractedRequirement(
        temp_id="S0-R1",
        description="Do not add a map.",
        polarity="exclude",
        source_quote="Please do not add a map to the search results.",
        source_timestamp="00:04:22",
        speaker="Priya Shah",
        status="confirmed",
        **base,
    )
    right = ExtractedRequirement(
        temp_id="S2-R1",
        description="Add a map.",
        polarity="include",
        source_quote="The board wants a map on the search results.",
        source_timestamp="00:23:10",
        speaker="Jordan Hale",
        status="confirmed",
        **base,
    )
    requirements, _decisions, questions = merge_extracts([left, right], [])
    if requirements[0].status != "disputed" or requirements[0].estimate_status != "blocked":
        raise RuntimeError("a contradiction was not left open")
    if not any(item.reason == "contradiction" for item in questions):
        raise RuntimeError("contradiction did not become an open question")

    removal = left.model_copy(
        update={
            "temp_id": "C-R1",
            "meeting_id": "mtg-c-search-followup",
            "source_timestamp": "00:03:30",
            "supersedes": True,
            "description": "Years in business is removed.",
            "topic_key": "filter_years_in_business",
        }
    )
    earlier = right.model_copy(
        update={
            "topic_key": "filter_years_in_business",
            "polarity": "include",
            "description": "Maybe filter by years in business.",
            "status": "unclear",
        }
    )
    superseded, _, superseded_questions = merge_extracts([earlier, removal], [])
    if superseded[0].polarity != "exclude" or superseded[0].status != "confirmed":
        raise RuntimeError("a later meeting did not replace the earlier requirement")
    if any(item.reason == "contradiction" for item in superseded_questions):
        raise RuntimeError("an explicit removal was treated as a contradiction")

    unsure_yes = left.model_copy(
        update={"temp_id": "W1", "topic_key": "filter_workshops", "polarity": "include", "status": "unclear"}
    )
    unsure_no = right.model_copy(
        update={"temp_id": "W2", "topic_key": "filter_workshops", "polarity": "exclude", "status": "unclear"}
    )
    workshops, _, workshop_questions = merge_extracts([unsure_yes, unsure_no], [])
    if workshops[0].status != "unclear" or any(item.reason == "contradiction" for item in workshop_questions):
        raise RuntimeError("an unclear deferral was treated as a contradiction")

    firm_no = left.model_copy(
        update={"temp_id": "H1", "topic_key": "homepage_redesign", "polarity": "exclude", "status": "confirmed"}
    )
    vague_yes = right.model_copy(
        update={"temp_id": "H2", "topic_key": "homepage_redesign", "polarity": "include", "status": "unclear"}
    )
    homepage, _, homepage_questions = merge_extracts([firm_no, vague_yes], [])
    if homepage[0].polarity != "exclude" or homepage[0].status != "confirmed":
        raise RuntimeError("a confirmed refusal lost to an unclear wish")
    if any(item.reason == "contradiction" for item in homepage_questions):
        raise RuntimeError("a confirmed refusal became a contradiction")

    sample = Requirement(
        id="REQ-001",
        description="Show member and guest prices.",
        source_quote="There are two prices.",
        source_timestamp="00:02:15",
        speaker="Sam Okonkwo",
        status="confirmed",
        priority="high",
        explicitness="explicit",
        existing_solution="Not established.",
        estimate_status="estimated",
        topic_key="checkout_member_guest_price",
        polarity="include",
        meeting_id="mtg-b-checkout",
        meeting_date="2026-10-18",
    )
    feasibility = [
        FeasibilityItem(
            requirement_id="REQ-001",
            classification="needs_clarification",
            kb_evidence="weak",
            kb_answer="not enough evidence",
            sources=[],
            verification_status="unverified",
            feature_absence_claimed=False,
            rationale="Missing evidence is not absence.",
            existing_solution="Not established. A missing or weak knowledge result is not proof the feature does not exist.",
        )
    ]
    bad = ProposalDocument(
        sections=[
            ProposalSection(key=key, heading=heading, body="We will integrate Stripe in April 2026 for $500.")
            for key, heading in __import__("app.schemas", fromlist=["PROPOSAL_SECTIONS"]).PROPOSAL_SECTIONS
        ]
    )
    errors = check_proposal(bad, [sample], feasibility, 4, None)
    if not errors:
        raise RuntimeError("proposal validator accepted a price, a date, and an integration promise")
    _ = Decision
    print("selfcheck ok")


if __name__ == "__main__":
    run_selfcheck()
