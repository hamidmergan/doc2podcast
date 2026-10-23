"""The model call that turns material into a conversation, and the check of its answer."""

import json
import logging
import re
from typing import List, Optional

from . import instructions
from .errors import ScriptUnusable
from .limits import MAX_LINE_CHARS, MAX_LINES
from .schemas import Line, PodcastParams, length_plan

logger = logging.getLogger(__name__)

_ROLE_DE = {
    "host": "Moderation, führt durch die Folge, fragt nach und bringt eigene Beobachtungen und Beispiele ein",
    "expert": "Fachperson, erklärt die Sache und bringt Beispiele",
    "student": "Studierende Person, fragt nach, wenn etwas unklar bleibt",
    "critic": "Kritische Stimme, benennt Grenzen und Einwände",
}
_ROLE_EN = {
    "host": "host, leads through the episode, asks back and brings own observations and examples",
    "expert": "expert, explains the matter and brings examples",
    "student": "student, asks again when something stays unclear",
    "critic": "critical voice, names limits and objections",
}
_STYLE_DE = {
    "teaching": "erklärend und anschaulich, Schritt für Schritt",
    "casual": "locker und gesprächig, auch mal ein Scherz",
    "interview": "Interview, kurze Fragen und ausführliche Antworten",
}
_STYLE_EN = {
    "teaching": "explanatory and vivid, step by step",
    "casual": "casual and chatty, the odd joke is fine",
    "interview": "interview, short questions and long answers",
}


def _cast(params: PodcastParams) -> str:
    roles = _ROLE_DE if params.language == "de" else _ROLE_EN
    return "\n".join(
        f"{i}: {p.name} ({roles.get(p.role, p.role)})" for i, p in enumerate(params.persons)
    )


def part_lengths(count: int, parts: int) -> List[int]:
    """How many contributions each part of the episode gets, the first ones one more."""
    parts = max(1, min(parts, count))
    base, rest = divmod(count, parts)
    return [base + (1 if i < rest else 0) for i in range(parts)]


def _frame_de(part: int, parts: int) -> str:
    if parts == 1:
        return "- Der erste Beitrag begrüßt und nennt das Thema, der letzte verabschiedet.\n"
    if part == 1:
        return ("- Der erste Beitrag begrüßt und nennt das Thema der ganzen Folge, wie der Plan "
                "es zeigt, nicht nur das dieses Teils. Die Folge geht danach weiter, also keine "
                "Verabschiedung.\n")
    if part == parts:
        return ("- Du setzt ein laufendes Gespräch fort, keine Begrüßung. "
                "Der letzte Beitrag verabschiedet.\n")
    return "- Du setzt ein laufendes Gespräch fort, keine Begrüßung und keine Verabschiedung.\n"


def _frame_en(part: int, parts: int) -> str:
    if parts == 1:
        return "- The first contribution greets and names the topic, the last says goodbye.\n"
    if part == 1:
        return ("- The first contribution greets and names the topic of the whole episode as the "
                "plan shows it, not only that of this part. The episode goes on afterwards, so no "
                "goodbye.\n")
    if part == parts:
        return "- You continue a running conversation, no greeting. The last contribution says goodbye.\n"
    return "- You continue a running conversation, no greeting and no goodbye.\n"


def _so_far(so_far: List[Line], params: PodcastParams) -> str:
    if not so_far:
        return ""
    names = [p.name for p in params.persons]
    lines = "\n".join(f"{names[l.speaker] if l.speaker < len(names) else l.speaker}: {l.text}"
                      for l in so_far)
    head = "Bisher zuletzt gesagt" if params.language == "de" else "Said last so far"
    return f"{head}:\n{lines}\n\n"


def _covered(openings: Optional[List[str]], head: str) -> str:
    if not openings:
        return ""
    return f"{head}:\n" + "\n".join(f"- {a}" for a in openings) + "\n\n"


def _shape(alone: bool) -> str:
    """The shape of one contribution, in a conversation it names its length before the text."""
    if alone:
        return '{"speaker": 0, "text": "..."}'
    return '{"speaker": 0, "long": false, "text": "..."}'


def _conversation_de(count: int) -> str:
    long_ones = max(1, round(count / 3))
    return (
        "- Die Personen wechseln sich ab, niemand spricht zweimal hintereinander.\n"
        "- Jede Person kommt vor und behält ihre Rolle.\n"
        "- Ein Gespräch unter Gleichen, kein Frage-Antwort-Spiel: Jeder Beitrag ist mindestens "
        "ein ganzer Satz mit 12 oder mehr Wörtern, nur jeder achte darf kürzer sein. Eine "
        "schnelle Reaktion steht nie allein, sie eröffnet einen Beitrag, der mit einem eigenen "
        "Gedanken, einer Frage oder einem Beispiel weitergeht.\n"
        "- Die Worte sind fair verteilt: Niemand spricht weniger als halb so viel wie eine "
        "andere Person.\n"
        f"- Die Längen wechseln wie im echten Gespräch: Bei genau {long_ones} der {count} Beiträge "
        'steht "long": true, das sind längere Erklärungen, Beispiele oder Geschichten mit 35 bis '
        '60 Wörtern. Die übrigen haben "long": false und 12 bis 25 Wörter. Die langen sind über '
        "das ganze Gespräch verteilt, und jede Person hat welche.\n"
        "- Verbotene Anfangswörter: Genau, Absolut, Richtig, Stimmt, Super, Toll, Interessant — "
        "diese klingen hohl und kommen als erstes Wort gar nicht vor. Kein weiteres erstes Wort "
        f"kommt in diesen {count} Beiträgen öfter als zweimal vor.\n"
        f"- In diesen {count} Beiträgen fasst jede Person mindestens zweimal in eigenen Worten "
        "zusammen, was die andere gerade erklärt hat, und fragt, ob sie es richtig verstanden "
        "hat, bringt mindestens einmal ein eigenes Beispiel oder Erlebnis und zweifelt "
        "mindestens einmal an etwas, das die Antwort dann mit dem Material klärt. Wer moderiert, "
        "leitet außerdem zum nächsten Thema über.\n"
        "- Gesprochene, nicht geschriebene Sprache: Verkürzungen wie gibt's, hab, ist's, Sätze, "
        "die mit also, na ja, hm oder ich meine anfangen, ab und zu ein Satz, der abbricht und "
        "neu ansetzt.\n"
        "- Gefühle in Worten: Die Personen staunen, amüsieren sich, zweifeln oder sind von einem "
        "Gedanken begeistert und zeigen das mit dem, was sie sagen, und mit den Satzzeichen, ab "
        "und zu auch mit einem kleinen Scherz. Sie sprechen sich ab und zu mit Namen an, wer "
        "spricht nennt nur den Namen der anderen Person, nie den eigenen.\n"
        "- Alles wird genau so vorgelesen, wie es dasteht, also kein Lachen, keine Geräusche und "
        "keine Handlungen in Schriftform.\n"
    )


def _conversation_en(count: int) -> str:
    long_ones = max(1, round(count / 3))
    return (
        "- The people take turns, nobody speaks twice in a row.\n"
        "- Every person appears and keeps their role.\n"
        "- A conversation between equals, not questions and answers: every contribution is at "
        "least one full sentence of 12 words or more, only one in eight may be shorter. A quick "
        "reaction never stands alone, it opens a contribution that goes on with an own thought, "
        "a question or an example.\n"
        "- The words are spread fairly: nobody speaks less than half as much as another person.\n"
        f"- Lengths change like in real talk: exactly {long_ones} of the {count} contributions carry "
        '"long": true, these are longer explanations, examples or stories of 35 to 60 words. The '
        'others carry "long": false and have 12 to 25 words. The long ones are spread over the '
        "whole conversation, and every person has some.\n"
        "- These words NEVER open a contribution, not even once: Exactly, Absolutely, Right, "
        "Great, Sure, Indeed, Wow, Fascinating, Interesting. Use alternatives: 'That makes sense', "
        "'Hmm, wait', 'Oh interesting', 'I didn't know that', 'So', 'Well', 'And', the other "
        "person's name, or start straight with the thought. "
        f"No other first word appears more than twice in these {count} contributions.\n"
        f"- In these {count} contributions each person at least twice sums up in own words what "
        "the other just explained and checks whether they got it right, at least once brings an "
        "own example or experience, and at least once doubts something, which the answer then "
        "clears up with the material. Whoever hosts also leads over to the next subject.\n"
        "- Spoken, not written language: contractions like it's, don't, that's, sentences that "
        "start with so, well, right or I mean, now and then a sentence that breaks off and "
        "starts anew.\n"
        "- Feelings in words: the people are surprised, amused, doubtful or taken with an idea "
        "and show it in what they say and in the punctuation, now and then with a small joke. "
        "They address each other by name now and then, the speaker only ever names the other "
        "person, never themselves.\n"
        "- Everything is read aloud exactly as it stands, so no laughter, noises or actions in "
        "writing.\n"
    )


def _example(params: PodcastParams) -> str:
    """A short conversation on another subject, a model copies a shape far better than rules."""
    a = params.persons[0].name
    b = params.persons[1].name
    if params.language == "de":
        return (
            "\nSo klingt das Gespräch. Übernimm nur die Art zu sprechen, nie das Thema oder "
            "einzelne Sätze:\n"
            f"{a}: Moment, der Vermieter darf die ganze Kaution behalten, nur weil die Wohnung "
            "nicht blitzblank ist? Das klingt ganz schön hart.\n"
            f"{b}: Nicht ganz, und genau da irren sich die meisten. Er darf nur behalten, was der "
            "Schaden wirklich kostet, und er muss dir zeigen, was es war. Ein bisschen Staub oder "
            "ein schmutziger Backofen sind kein Grund, achthundert Euro einzubehalten. Stell's "
            "dir eher wie eine Versicherung für die Wohnung vor als wie eine Strafe.\n"
            f"{a}: Okay, wenn ich das richtig verstehe, ist das also ein Polster für echte "
            "Schäden und keine Strafe fürs Unordentlichsein?\n"
            f"{b}: Genau so. Und ehrlich? Die meisten fordern sie nie zurück.\n"
            f"{a}: Oh, das kenn ich. Als ich aus meiner ersten Wohnung ausgezogen bin, dachte ich "
            "nur, na ja, das Geld ist weg, und hab nie angerufen. Zwei Jahre später sagt mir eine "
            "Freundin, dass ich es hätte zurückfordern können, und da wusste ich... ich meine, da "
            "wusste ich nicht mal mehr, wo der Vermieter wohnt.\n"
            f"{b}: Da bist du wirklich nicht allein! Aber was ich spannend finde: Der Vermieter "
            "hat auch nicht ewig Zeit.\n"
            f"{a}: Hm, wie lange denn, ein paar Wochen?\n"
            f"{b}: Meist ein paar Monate. Und fehlt die Heizkostenabrechnung noch, darf er einen "
            f"Teil zurückhalten, {a}, aber eben nur einen Teil.\n"
        )
    return (
        "\nThis is how the conversation sounds. Take only the way of talking, never the subject "
        "or single sentences:\n"
        f"{a}: Wait, so the landlord can keep the whole deposit just because the flat isn't "
        "spotless? That sounds pretty harsh to me.\n"
        f"{b}: Not quite, and that's what most people get wrong. He can only keep what the "
        "damage really costs, and he has to show you what it was. A bit of dust or a dirty oven "
        "isn't a reason to hold on to eight hundred euros. Think of it more like insurance for "
        "the flat than a fine.\n"
        f"{a}: Okay, so if I get this right, it's a safety net for real damage, not a punishment "
        "for being messy?\n"
        f"{b}: That's it. And honestly? Most people never even ask for it back.\n"
        f"{a}: Oh, I know that one. When I moved out of my first flat, I just thought, well, "
        "that money's gone, and I never called. Two years later a friend tells me I could've "
        "asked for it, and by then... I mean, I didn't even know where the landlord lived "
        "anymore.\n"
        f"{b}: You're really not the only one! But here's the part I find interesting: the "
        "landlord doesn't get forever either.\n"
        f"{a}: Hm, how long are we talking, a few weeks?\n"
        f"{b}: Usually a few months. And if the heating bill isn't done yet, he can hold back a "
        f"part, {a}, but only a part.\n"
    )


def build_messages(source: str, params: PodcastParams, *, count: Optional[int] = None,
                   part: int = 1, parts: int = 1, plan: str = "",
                   so_far: Optional[List[Line]] = None, opening: str = "",
                   thread: str = "", covered: Optional[List[str]] = None) -> List[dict]:
    """One call, the answer is a JSON object with the list of contributions.

    A long episode is written in parts, each call writes few contributions and so stays
    inside the provider's few minutes. ``plan`` is the whole episode, ``so_far`` the last
    contributions before this part, ``opening`` the situation the first part starts with
    and ``thread`` what the last part closes on. ``covered`` holds the openings of all
    earlier contributions, so a later part does not explain the same thing again.
    """
    total, per_line = length_plan(params.minutes)
    count = count or total
    words = count * per_line
    alone = len(params.persons) == 1
    so_far = so_far or []
    if params.language == "de":
        system = (
            "Du schreibst das Skript einer Podcast-Folge für eine Hochschule. "
            "Fakten, Zahlen, Fristen und Bedingungen nimmst du ausschließlich aus dem gelieferten "
            "Material und fügst keine hinzu. Beispiele, Vergleiche und Einwände darfst du selbst "
            "bringen, damit die Sache anschaulich wird. "
            "Du antwortest mit einem JSON-Objekt der Form "
            f'{{"lines": [{_shape(alone)}]}} und mit nichts sonst.'
        )
        part_line = (f"Du schreibst Teil {part} von {parts} der Folge.\n"
                     f"Plan der ganzen Folge:\n{plan}\n\n") if parts > 1 else ""
        task = (
            f"{part_line}Material:\n---\n{source}\n---\n\n"
            f"{_covered(covered, 'Schon besprochen, nicht wiederholen')}"
            f"{_so_far(so_far, params)}"
            f"Besetzung, die Zahl ist der Wert für speaker:\n{_cast(params)}\n\n"
            f"Stil: {_STYLE_DE.get(params.style, params.style)}\n"
            f"Umfang: genau {count} Beiträge, zusammen rund {words} Wörter, im Schnitt {per_line} je Beitrag.\n\n"
            "Regeln:\n"
            "- Sprache des Skripts: Deutsch. Die Hörer werden durchgehend geduzt.\n"
            + ("- Es spricht nur eine Person, speaker ist immer 0.\n" if alone
               else _conversation_de(count))
            + f"- Im Schnitt etwa {per_line} Wörter je Beitrag, nie mehr als 150.\n"
            "- Wenige Punkte in der Tiefe statt einer Aufzählung: zu jeder Regel, warum es sie "
            "gibt, was aus ihr folgt und ein Beispiel aus dem Alltag der Hörer. Gern auch ein "
            "Einwand oder ein verbreiteter Irrtum, den die Antwort mit dem Material auflöst.\n"
            + _frame_de(part, parts)
            + (f"- Nach der Begrüßung erzählt eine Person diese kleine Geschichte, lebendig und "
               f"in eigenen Worten, und das Gespräch greift ihre Frage auf: {opening}\n"
               if part == 1 and opening else "")
            + ("- Vor der Verabschiedung kommt das große Bild, das alle Themen der Folge "
               "verbindet, und ein Gedanke, den die Hörer mitnehmen, gern als offene Frage"
               + (f": {thread}" if thread else "") + ".\n" if part == parts else "")
            + ("- Wiederhole nichts, was bisher schon gesagt wurde.\n" if so_far else "")
            + (f"- Der letzte Beitrag bisher kam von speaker {so_far[-1].speaker}, dein erster "
               "Beitrag kommt von jemand anderem.\n" if so_far and not alone else "")
            + ("- Die Teile sind nur Arbeitsschritte. Für die Hörer ist es ein einziges "
               "Gespräch, erwähne nie einen Teil.\n" if parts > 1 else "")
            + "- Keine Regieanweisungen, keine Namen vor dem Text, keine Zwischenüberschriften.\n"
            "- Zahlen und Formeln ausschreiben, der Text wird vorgelesen.\n"
            "- Die Zeilen in eckigen Klammern im Material nennen nur Datei und Seite, lies sie nie vor.\n"
        )
    else:
        system = (
            "You write the script of a podcast episode for a university. "
            "Facts, figures, deadlines and conditions come only from the material provided and "
            "you add none. Examples, comparisons and objections you may bring yourself, so the "
            "matter becomes vivid. "
            "You answer with a JSON object of the form "
            f'{{"lines": [{_shape(alone)}]}} and nothing else.'
        )
        part_line = (f"You write part {part} of {parts} of the episode.\n"
                     f"Plan of the whole episode:\n{plan}\n\n") if parts > 1 else ""
        task = (
            f"{part_line}Material:\n---\n{source}\n---\n\n"
            f"{_covered(covered, 'Already covered, do not repeat')}"
            f"{_so_far(so_far, params)}"
            f"Cast, the number is the value for speaker:\n{_cast(params)}\n\n"
            f"Style: {_STYLE_EN.get(params.style, params.style)}\n"
            f"Length: exactly {count} contributions, {words} words in total, {per_line} per contribution on average.\n\n"
            "Rules:\n"
            "- Language of the script: English.\n"
            + ("- Only one person speaks, speaker is always 0.\n" if alone
               else _conversation_en(count))
            + f"- About {per_line} words per contribution on average, never more than 150.\n"
            "- Few points in depth instead of a list: for each rule why it exists, what "
            "follows from it and an example from the listeners' everyday life. An objection or "
            "a common misconception that the answer clears up with the material is welcome.\n"
            + _frame_en(part, parts)
            + (f"- After the greeting one person tells this small story, vividly and in their own "
               f"words, and the conversation takes up its question: {opening}\n"
               if part == 1 and opening else "")
            + ("- Before the goodbye comes the big picture that connects all subjects of the "
               "episode, and one thought the listeners take home, maybe as an open question"
               + (f": {thread}" if thread else "") + ".\n" if part == parts else "")
            + ("- Repeat nothing that was already said.\n" if so_far else "")
            + (f"- The last contribution so far was by speaker {so_far[-1].speaker}, your first "
               "contribution comes from someone else.\n" if so_far and not alone else "")
            + ("- The parts are only working steps. For the listeners it is one single "
               "conversation, never mention a part.\n" if parts > 1 else "")
            + "- No stage directions, no names before the text, no headings.\n"
            "- Spell out numbers and formulas, the text is read aloud.\n"
            "- The lines in square brackets in the material only name file and page, never read them out.\n"
        )
    if not alone:
        task += _example(params)
    task += instructions.write_addition(params.instructions, params.instruction_way)
    return [{"role": "system", "content": system}, {"role": "user", "content": task}]


def plan_messages(material: str, params: PodcastParams, parts: int,
                  files: Optional[List[str]] = None) -> List[dict]:
    """The episode laid out in parts, each with its own subject."""
    language = "German" if params.language == "de" else "English"
    # An instruction with a subject of its own decides what the episode is about, not the files.
    if instructions.focus(params.instructions, params.instruction_way):
        files = None
    system = (
        "You plan a podcast episode for university teaching. From the material you pick what "
        f"matters to the listeners and lay the episode out in exactly {parts} consecutive "
        "parts, each with its own subject. Order the parts by what affects the listeners most, "
        "and where documents touch the same subject bring them together, never one file after "
        "the other. Leave out administrative detail on how bodies are organised, elected, "
        "staffed or financed unless the material is mainly about that.\n"
        f"Write titles, gists, opening and thread in {language}.\n"
        + (f"The material comes from {len(files)} files: {', '.join(files)}. EVERY one of "
           "them is talked about in the episode.\n" if files and len(files) > 1 else "")
        + 'Answer with one JSON object only: {"opening": "...", "thread": "...", "parts": '
        '[{"title": "...", "gist": "..."}]}. The opening is a '
        "small story: one person in one concrete situation from the listeners' own life that "
        "the material decides, ending in a question the episode answers, in two or three "
        "sentences, ideally touching several of the documents, never a list of problems. The thread is one "
        "sentence on what connects all documents, the thought the listeners take home. Both "
        "span the whole material, not the frame of the largest one. The gist is one sentence saying what that part covers and "
        "which question it answers."
    )
    task = f"/no_think\nMATERIAL:\n{material}\n"
    task += instructions.plan_addition(params.instructions, params.instruction_way, "part")
    return [{"role": "system", "content": system}, {"role": "user", "content": task}]


# A model sometimes copies numbers into the gist, "... refs: [21-32]".
_REFS_IN_TEXT = re.compile(r"\s*\brefs?\s*:.*$", re.IGNORECASE)


def parse_plan(raw: str, parts: int) -> List[dict]:
    """The parts out of the planning answer.

    Too many parts are folded into the last one, too few stay as they are: the episode
    is then written in fewer calls, each still small enough.
    """
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ScriptUnusable("no JSON braces in the plan")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ScriptUnusable(f"no valid JSON in the plan: {exc}") from exc
    raw_parts = data.get("parts") if isinstance(data, dict) else None
    out: List[dict] = []
    for entry in raw_parts if isinstance(raw_parts, list) else []:
        if not isinstance(entry, dict):
            continue
        title = " ".join(str(entry.get("title") or "").split())[:120]
        if not title:
            continue
        gist = _REFS_IN_TEXT.sub("", " ".join(str(entry.get("gist") or "").split()))
        out.append({"title": title, "gist": gist.strip()[:300]})
    if not out:
        raise ScriptUnusable("the plan holds no part")
    while len(out) > parts:
        out.pop()
    for part in out:
        part["opening"] = part["thread"] = ""
    out[0]["opening"] = " ".join(str(data.get("opening") or "").split())[:400]
    out[-1]["thread"] = " ".join(str(data.get("thread") or "").split())[:300]
    return out


def without_self_address(lines: List[Line], names: List[str]) -> List[Line]:
    """A speaker never addresses themselves, a model that mixes up the cast does."""
    out: List[Line] = []
    for line in lines:
        name = names[line.speaker] if line.speaker < len(names) else ""
        text = line.text
        if name:
            n = re.escape(name)
            text = re.sub(rf"^\s*{n}\s*[,!]\s*", "", text)
            text = re.sub(rf",\s*{n}\b(?=\s*[.!?,])", "", text)
            text = text[:1].upper() + text[1:]
        out.append(line.model_copy(update={"text": text}) if text != line.text else line)
    return out


def parse_answer(raw: str, person_count: int) -> List[Line]:
    """The model's answer to lines, with every rule checked that costs us later."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ScriptUnusable("no JSON braces in the answer")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ScriptUnusable(f"no valid JSON: {exc}") from exc

    raw_lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ScriptUnusable("the answer holds no contribution")

    lines: List[Line] = []
    for entry in raw_lines[:MAX_LINES]:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("text") or "").strip()
        if not content:
            continue
        try:
            speaker = int(entry.get("speaker", 0))
        except (TypeError, ValueError):
            speaker = 0
        # Wrapped instead of clamped: a stray index must not collapse the conversation
        # onto one voice and take the whole script down with it.
        speaker = speaker % person_count if person_count else 0
        lines.append(Line(speaker=speaker, text=content[:MAX_LINE_CHARS]))

    if len(lines) < 2:
        raise ScriptUnusable(f"only {len(lines)} usable contributions")
    if person_count > 1 and len({l.speaker for l in lines}) < 2:
        raise ScriptUnusable("only one person appears although several are cast")
    logger.info("Podcast: %d contributions, %d voices", len(lines), len({l.speaker for l in lines}))
    return lines
