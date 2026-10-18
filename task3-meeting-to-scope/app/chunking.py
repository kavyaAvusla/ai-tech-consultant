from __future__ import annotations

from app.config import SECTION_OVERLAP, SECTION_WINDOW
from app.schemas import Section, Transcript


def render_turns(transcript: Transcript, start: int, end: int) -> str:
    lines = []
    for turn in transcript.turns[start:end]:
        lines.append(f"[{turn.timestamp}] {transcript.speaker_name(turn.speaker_id)}: {turn.text}")
    return "\n".join(lines)


def split_transcript(
    transcript: Transcript,
    window: int = SECTION_WINDOW,
    overlap: int = SECTION_OVERLAP,
) -> list[Section]:
    count = len(transcript.turns)
    if window <= overlap:
        raise ValueError("section window must be larger than the overlap")
    ranges: list[tuple[int, int]] = []
    if count <= window:
        ranges.append((0, count))
    else:
        start = 0
        while start < count:
            end = min(count, start + window)
            ranges.append((start, end))
            if end == count:
                break
            start = end - overlap
    sections: list[Section] = []
    for index, (start, end) in enumerate(ranges):
        turns = transcript.turns[start:end]
        sections.append(
            Section(
                section_index=index,
                turn_start=start,
                turn_end=end,
                start_timestamp=turns[0].timestamp,
                end_timestamp=turns[-1].timestamp,
                text=render_turns(transcript, start, end),
            )
        )
    return sections
