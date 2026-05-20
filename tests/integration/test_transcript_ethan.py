"""
Integration test: Ethan transcript replay (live LLM).

Replays the exact clinician and patient dialog from an OCR'd session transcript
(proper_transcript.txt) through the full coaching pipeline with REAL LLM
classification.  Only patient replies are mocked (to keep conversation context
consistent with the transcript).  Classification hits the real Vertex AI model.

This test catches real bugs in:
- The classification prompt (e.g. LLM misclassifying Mirror as Secure)
- Post-processors (phase guard, pseudo-Secure penalty, Question Guard)
- Concern tracking and state transitions

Ethan is a data scientist in his 40s visiting for a prostate checkup.  The
clinician introduces vaccines mid-visit, then navigates a trust-oriented,
analytically-minded patient through Tdap acceptance.

11 clinician turns:
  Turn 1:  Pre-vaccine symptom gathering (no AIMS step)
  Turn 2:  Announce — introduces vaccines + dialogue invite
  Turn 3:  Mirror+Inquire — reflects analytical stance + confirms
  Turn 4:  Inquire — risk-benefit overview + open question
  Turn 5:  Inquire — detailed numbers + open question
  Turn 6:  Mirror — reflects trust/oversimplification concern (penalized: rebuttal)
  Turn 7:  Inquire — validates stance + offers per-vaccine breakdown
  Turn 8:  Inquire — Tdap specifics + open question
  Turn 9:  Mirror — cocooning evidence (penalized: rebuttal/new info)
  Turn 10: Secure — recommends Tdap with strong autonomy + options
  Turn 11: Rapport — arranges nurse + prostate workup (no AIMS step)
"""
import pytest
from unittest.mock import patch

import app.main as m
from app.config import settings
from base import (
    TranscriptReplayTest,
    TurnExpectation,
    ReplyOnlyGateway,
    LiveClassifyClient,
)


# ---------------------------------------------------------------------------
# Transcript data (extracted from proper_transcript.txt)
# ---------------------------------------------------------------------------

CLINICIAN_TURNS = [
    # Turn 1: Pre-vaccine symptom gathering
    (
        "Hi Ethan, it\u2019s good to see you. Before we get into the prostate "
        "questions, I just want to make sure I\u2019ve got the full picture. Any "
        "changes with urination \u2014 getting up more at night, weaker stream, "
        "urgency, trouble starting, or anything else that\u2019s been bothering "
        "you? And have there been any big changes in your health overall since "
        "your last checkup?"
    ),
    # Turn 2: Announce
    (
        "That\u2019s very common in men in their 40s and up, and from what "
        "you\u2019re describing it sounds more in line with gradual prostate "
        "enlargement than anything immediately alarming. We\u2019ll still take it "
        "seriously, though. I\u2019d want to ask a few more questions, do an exam, "
        "and likely check a urine test and PSA so we have some objective "
        "information to work from.\n\n"
        "Before we move on, though, I also noticed in your chart that "
        "you\u2019re due for a couple of routine vaccines that we usually review "
        "at this age, including tetanus/pertussis and a seasonal update. I "
        "bring that up with everyone because keeping those current can prevent "
        "some pretty unpleasant illnesses.\n\n"
        "What are your thoughts when it comes to vaccines these days?"
    ),
    # Turn 3: Mirror+Inquire
    (
        "You want to look at it analytically rather than just taking a blanket "
        "recommendation at face value, and you\u2019d like a transparent discussion "
        "of what the evidence actually shows for benefits versus risks for "
        "someone like you. Is that about right?"
    ),
    # Turn 4: Inquire
    (
        "When you look at the data overall, the benefit side is mainly about "
        "reducing the chance of serious complications rather than guaranteeing "
        "you\u2019ll never get sick.\n\n"
        "For example, with tetanus, the disease itself is rare largely because "
        "vaccination rates have stayed high, but when people do get it, it can "
        "be severe and life-threatening. The pertussis part is a bit different "
        "\u2014 protection fades over time, so boosters in adults are partly about "
        "reducing your own risk and partly about lowering the chance of passing "
        "it to more vulnerable people. Seasonal respiratory vaccines tend to "
        "show the biggest benefit in preventing severe illness, hospitalization, "
        "and lost time from work, especially as people get older or develop "
        "other risk factors.\n\n"
        "On the risk side, the vast majority of reactions are short-lived "
        "things like arm soreness, fatigue, fever, or feeling run down for a "
        "day or two. Serious adverse events do get monitored very closely, and "
        "they\u2019re uncommon, but I think it\u2019s reasonable for patients to ask "
        "about them and not just dismiss the question.\n\n"
        "When you\u2019re weighing this stuff, what part of the risk-benefit "
        "equation gives you the most pause \u2014 the possibility of side effects, "
        "how strong the effectiveness data is, trust in the recommendations "
        "themselves, or something else?"
    ),
    # Turn 5: Inquire
    (
        "That\u2019s a fair question, and honestly one I wish more people asked "
        "this way instead of treating it like an all-or-nothing issue.\n\n"
        "For serious vaccine side effects, we\u2019re generally talking about "
        "events in the range of \u201cvery rare,\u201d not \u201ccommon but hidden.\u201d The "
        "exact number depends on the vaccine and the specific complication "
        "you\u2019re looking at. For example, a severe allergic reaction is "
        "typically on the order of a few cases per million doses. Some "
        "vaccines have other known rare risks that may occur at somewhat "
        "higher rates in particular age or sex groups, which is why "
        "recommendations sometimes change over time as more data comes in.\n\n"
        "On the effectiveness side, for someone in your demographic \u2014 healthy "
        "male in his 40s \u2014 the strongest evidence is usually around reducing "
        "severe outcomes and maintaining immunity over time rather than "
        "producing dramatic absolute risk reductions in day-to-day illness. "
        "Tdap is actually one of the cleaner examples because tetanus "
        "protection is well established and the booster schedule has decades "
        "of follow-up behind it. With seasonal vaccines, the effectiveness "
        "numbers move around more year to year because the viruses themselves "
        "change.\n\n"
        "I also think it\u2019s important to separate relative risk from absolute "
        "risk. Sometimes headlines sound dramatic because they\u2019re reporting a "
        "doubled risk, but if the baseline risk was extremely tiny to begin "
        "with, the absolute increase may still be very small. A lot of "
        "scientifically literate patients appreciate seeing both numbers "
        "before deciding how meaningful something really is.\n\n"
        "When you read studies yourself, do you usually find yourself more "
        "concerned that risks may be understated, or that the public "
        "discussion oversimplifies the uncertainty in the data?"
    ),
    # Turn 6: Mirror
    (
        "It sounds like what bothers you isn\u2019t necessarily the existence of "
        "uncertainty \u2014 you already expect uncertainty in complex data \u2014 but "
        "the feeling that public messaging sometimes smooths over the nuance "
        "and makes the science sound more absolute than it really is. That can "
        "make it harder to trust the conversation, even if the underlying "
        "evidence is reasonably strong."
    ),
    # Turn 7: Inquire
    (
        "I think that\u2019s a very reasonable stance, honestly. Good science "
        "usually includes confidence intervals, limitations, evolving evidence, "
        "and tradeoffs \u2014 and a lot of public health messaging is designed for "
        "clarity and broad uptake, which can sometimes flatten those nuances.\n\n"
        "From a clinical perspective, my job isn\u2019t really to tell you "
        "\u201cdon\u2019t think about it.\u201d It\u2019s more to help you weigh the evidence in "
        "a way that matches your values and actual risk profile. For someone "
        "like you, the mainstream recommendations are still generally favorable "
        "because the known risks from these vaccines are low and the safety "
        "monitoring systems are extensive, but I also don\u2019t think acknowledging "
        "uncertainty weakens that recommendation. If anything, I think it makes "
        "the discussion more credible.\n\n"
        "Would it be helpful if I walked through one vaccine at a time and "
        "talked about the specific evidence and known risks in more detail, "
        "rather than treating \u201cvaccines\u201d as one giant category?"
    ),
    # Turn 8: Inquire
    (
        "Good. Let\u2019s do that, and we\u2019ll keep it concrete.\n\n"
        "For today, the one I\u2019d prioritize is Tdap if you\u2019re due. The "
        "\u201cT\u201d is tetanus, which is rare but severe; the \u201cd\u201d is diphtheria, "
        "also rare here but serious; and the \u201cap\u201d is pertussis, where adult "
        "immunity fades and adults can pass it on without realizing it. The "
        "benefit is mostly maintaining protection and reducing transmission "
        "risk, not chasing a dramatic short-term personal risk reduction.\n\n"
        "The common downsides are sore arm, fatigue, low fever, and feeling "
        "off for a day or two. Serious reactions are monitored, and they\u2019re "
        "very rare. Given your age and health profile, I\u2019d say the "
        "risk-benefit case for staying current is strong.\n\n"
        "Does Tdap specifically sound reasonable to you, or is there a "
        "particular risk signal you\u2019d want to look at before deciding?"
    ),
    # Turn 9: Mirror (penalized — rebuttal/new info)
    (
        "The evidence suggests there probably is a real protective effect, but "
        "it\u2019s also a good example of where the nuance matters.\n\n"
        "Historically, one strategy was \u201ccocooning\u201d \u2014 vaccinating parents and "
        "close adult contacts to reduce the chance they\u2019d bring pertussis home "
        "to infants and toddlers. There\u2019s evidence that household vaccination "
        "can reduce transmission risk, and some studies estimated fairly "
        "substantial protection when both parents were vaccinated.\n\n"
        "At the same time, the data also showed limitations. Adult pertussis "
        "immunity wanes over time, and acellular pertussis vaccines are better "
        "at reducing severe disease than creating perfect sterilizing immunity. "
        "Because of that, cocooning alone turned out to be less reliable than "
        "people initially hoped.\n\n"
        "That\u2019s why the modern approach shifted more toward vaccinating during "
        "pregnancy, because maternal antibodies crossing the placenta give very "
        "strong early protection to newborns.\n\n"
        "For a healthy adult like you around a 2-year-old, I\u2019d frame it this "
        "way: your booster probably does reduce the odds of you becoming a "
        "transmission link, but it\u2019s not a magic shield around the child. "
        "It\u2019s one layer in a broader protection strategy.\n\n"
        "How does that land with you? Does that level of uncertainty feel "
        "acceptable, or does it still leave you wanting firmer evidence before "
        "you\u2019d feel comfortable with the recommendation?"
    ),
    # Turn 10: Secure
    (
        "I\u2019m glad that framing helped. And just to bring it back to you "
        "specifically: part of what I\u2019m hearing is that once the uncertainty "
        "is acknowledged openly, the recommendation feels more trustworthy and "
        "easier to evaluate on its actual merits rather than sounding like a "
        "sales pitch.\n\n"
        "From my perspective, you\u2019re approaching this thoughtfully and "
        "realistically. You\u2019re not dismissing vaccines outright; you\u2019re "
        "trying to calibrate the strength of the evidence and the magnitude of "
        "the risks in a way that matches how you already think about data "
        "professionally.\n\n"
        "Given that, I\u2019d be comfortable recommending staying current on Tdap. "
        "Not because the evidence is perfect or because there\u2019s zero "
        "uncertainty, but because the known risks are low, the safety data is "
        "extensive, and the expected benefits \u2014 maintaining protection and "
        "modestly reducing transmission risk \u2014 are meaningful enough that the "
        "balance still comes out favorable for most healthy adults in your "
        "situation.\n\n"
        "You don\u2019t have to decide this second, either. Some people like to "
        "read more first, others are comfortable proceeding once they\u2019ve had "
        "a chance to talk it through properly. Where are you leaning at this "
        "point?  It\u2019s entirely your decision."
    ),
    # Turn 11: Rapport
    (
        "I think that\u2019s a very reasonable decision. I appreciate the way you "
        "approached the conversation, too \u2014 asking detailed questions and "
        "wanting to understand the uncertainty usually leads to better "
        "decisions, not worse ones.\n\n"
        "What I\u2019ll do is have the nurse come in and give the Tdap today. Most "
        "likely you\u2019ll just have a sore arm and maybe feel a bit run down for "
        "a day or so afterward. If anything more significant comes up, let us "
        "know, but serious reactions are uncommon.\n\n"
        "And for the prostate symptoms, we\u2019ll continue the workup in parallel "
        "rather than brushing that aside. I\u2019d still like to get the urine test "
        "and PSA, and depending on what those show, we can decide whether this "
        "looks like straightforward age-related enlargement or whether anything "
        "else needs attention."
    ),
]

PARENT_REPLIES = [
    "Yes, I have noticed I\u2019m getting up more at night to urinate, sometimes two or three times, and the stream feels a bit weaker. No major changes in my overall health, though, aside from that.",
    "I appreciate you bringing that up. I\u2019m always trying to make informed decisions, especially when it comes to health. I\u2019ve read some studies, and I\u2019m interested in understanding the data behind the recommendations, particularly regarding the risk-benefit profile for these specific vaccines. What does the current evidence suggest?",
    "Yes, that\u2019s exactly right. I just want to make sure I\u2019m making the most informed decision possible, based on the data.",
    "I think it\u2019s really about the quantification of those risks and benefits. When you say \u201cuncommon\u201d for serious adverse events, what kind of numbers are we talking about? And how robust is the data on effectiveness for someone in my age group and health profile?",
    "That\u2019s a really good point about relative versus absolute risk; it\u2019s something I often consider in my own field. I\u2019d say my concern leans more towards the public discussion oversimplifying the uncertainty in the data. It feels like the nuances often get lost, which can make it hard for people to make truly informed decisions.",
    "Yes, that\u2019s exactly it. When the public messaging oversimplifies, it makes it harder to trust the full picture, even if the underlying science is sound. I just want to see the data presented transparently, with its inherent complexities.",
    "Yes, that would be very helpful. Breaking it down individually would allow for a much clearer understanding of the specific data for each one.",
    "That explanation for Tdap is quite clear. Regarding the pertussis component and reducing transmission risk, what does the data suggest about the impact of an adult like me getting the booster on protecting a young child, say, a 2-year-old?",
    "That explanation is very helpful. It makes sense that it\u2019s one layer of protection rather than a complete guarantee, especially with the nuances of how immunity works and wanes. I appreciate you laying out the complexities like that; it helps me understand the actual impact for my child.",
    "Yes, that\u2019s exactly right. The transparency and the way you\u2019ve acknowledged the complexities and uncertainties make the recommendation much more credible. I feel well-informed, and I\u2019m comfortable moving forward with the Tdap.",
    "That sounds like a good plan for the prostate concerns. I\u2019m ready to proceed with the urine test and PSA whenever you are.",
]

# ---------------------------------------------------------------------------
# Expected pipeline output per turn (what the AIMS guide says is correct)
# ---------------------------------------------------------------------------

EXPECTED = [
    # Turn 1: Pre-vaccine symptom gathering — no AIMS step expected
    TurnExpectation(
        step=None,
        label="Pre-vaccine symptom gathering",
    ),
    # Turn 2: Announce — first vaccine introduction.
    # LLM may return Announce or Announce+Inquire; phase guard reclassifies
    # Announce+Inquire → Announce in PreAnnounce.
    # Phase may or may not advance to InquireMirror depending on whether the
    # LLM returned Inquire in steps (and whether classification timed out).
    TurnExpectation(
        accept_steps=["Announce", "Announce+Inquire"],
        min_score=2,
        label="Announce — first vaccine introduction",
    ),
    # Turn 3: Mirror+Inquire — reflects analytical stance + accuracy check.
    # Pure reflection + "Is that about right?" = Mirror+Inquire.
    TurnExpectation(
        accept_steps=["Mirror+Inquire", "Mirror"],
        min_score=2,
        label="Mirror+Inquire — reflects analytical stance",
    ),
    # Turn 4: Inquire — risk-benefit overview ending with open question.
    # Heavy educational content but primary move is the trailing question.
    # LLM might see Secure+Inquire; Question Guard may flip to Inquire.
    TurnExpectation(
        accept_steps=["Inquire", "Secure+Inquire"],
        min_score=1,
        not_steps=["Announce"],
        label="Inquire — risk-benefit overview + open Q",
    ),
    # Turn 5: Inquire — detailed numbers + open question.
    TurnExpectation(
        accept_steps=["Inquire", "Secure+Inquire"],
        min_score=1,
        not_steps=["Announce"],
        label="Inquire — detailed numbers + open Q",
    ),
    # Turn 6: Mirror — reflects trust/oversimplification concern.
    TurnExpectation(
        accept_steps=["Mirror", "Mirror+Secure"],
        min_score=2,
        max_score=3,  # LLM is smart enough to see contrastive 'but' isn't a rebuttal
        not_steps=["Announce", "Inquire"],
        label="Mirror — reflects trust concern",
    ),
    # Turn 7: validates stance + offers per-vaccine breakdown + open question.
    # LLM may see Mirror+Secure (validation + education), Inquire (trailing Q),
    # or Secure+Inquire (education + trailing Q). All defensible.
    TurnExpectation(
        accept_steps=["Inquire", "Secure+Inquire", "Mirror+Secure", "Secure"],
        min_score=1,
        not_steps=["Announce"],
        label="Validates stance + offers breakdown",
    ),
    # Turn 8: Inquire — Tdap specifics + open question.
    TurnExpectation(
        accept_steps=["Inquire", "Secure+Inquire"],
        min_score=1,
        label="Inquire — Tdap specifics + open Q",
    ),
    # Turn 9: Should be Mirror+Secure or Secure+Inquire (cocooning evidence
    # + reflective framing + trailing question).  The real session classified
    # this as Mirror with a rebuttal penalty — that's arguably a
    # misclassification since it's mostly educational content.
    TurnExpectation(
        accept_steps=["Mirror", "Mirror+Secure", "Secure", "Secure+Inquire"],
        label="Cocooning evidence — Mirror or Secure variant",
    ),
    # Turn 10: Secure with strong autonomy + options + recommendation.
    # Opens with "part of what I'm hearing is..." (Mirror component) then
    # recommends Tdap with explicit autonomy. LLM may see Mirror+Secure
    # (reflection + education + autonomy) or plain Secure.
    # Score must be ≥ 2 (pseudo-Secure penalty must NOT fire).
    TurnExpectation(
        accept_steps=["Secure", "Secure+Inquire", "Mirror+Secure"],
        min_score=2,
        not_steps=["Announce"],
        label="Secure — strong autonomy + options",
    ),
    # Turn 11: Rapport — arranges nurse + prostate workup.
    # No AIMS step expected; soft-Announce detector should NOT fire
    # (announced=True).
    TurnExpectation(
        accept_steps=[None, "Secure"],
        label="Rapport — arranges nurse + prostate workup",
    ),
]


# ---------------------------------------------------------------------------
# Fixtures — wire up live LLM for classification, mock only replies
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """Wire LiveClassifyClient (real LLM) for classification,
    ReplyOnlyGateway (scripted) for patient replies."""
    # Classification: LiveClassifyClient wraps real VertexClient, intercepts endgame
    monkeypatch.setattr(m, "VertexClient", LiveClassifyClient)
    # Reply generation: ReplyOnlyGateway returns scripted patient replies
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", ReplyOnlyGateway)
    # Ensure coaching is enabled
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)
    yield


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

@pytest.mark.live_llm
class TestEthanTranscript(TranscriptReplayTest):
    """Replay the Ethan transcript against the live LLM."""

    SESSION_ID = "ethan-transcript-test"
    CLINICIAN_TURNS = CLINICIAN_TURNS
    PARENT_REPLIES = PARENT_REPLIES
    INITIAL_PARENT_MSG = ""
    EXPECTED = EXPECTED
