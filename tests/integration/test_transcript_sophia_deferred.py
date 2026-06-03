"""
Integration test: Sophia transcript replay (live LLM).

Replays the dialog from conversation.json plus two extra turns.
Uses live LLM for classification.
"""
import pytest

import app.main as m
from app.config import settings
from .base import (
    TranscriptReplayTest,
    TurnExpectation,
    ReplyOnlyGateway,
    LiveClassifyClient,
)

CLINICIAN_TURNS = [
    # Turn 1
    (
        "Hi Jasmine, it’s good to see you and Sophia today. First off, how have the last couple of months been going for you both? Two-month visits can be a lot when you’re running on very little sleep.\n\n"
        "I’ve had a look at Sophia, and overall she’s looking well today. We’ll go over her growth, feeding, sleep, and development, and I also see it’s time for her 2-month vaccines.\n\n"
        "Before we get into that part, what questions or worries have been on your mind about the vaccines?"
    ),
    # Turn 2
    (
        "Hi Jasmine, it’s good to see you and Sophia today. First of all, how have things been going at home? Two months in with a newborn can be exhausting, so I always like to check in on the parents too.\n\n"
        "From what you’ve told me so far, Sophia sounds like she’s doing well overall. Today I’ll examine her, check her growth and development, and make sure feeding, sleep, and diapers are all on track. If anything has been worrying you about her health or behavior, we can absolutely talk through it.\n\n"
        "I also see that Sophia is due for her 2-month vaccines today. These are the routine immunizations we recommend at this age to help protect babies from some serious infections while their immune systems are still developing."
    ),
    # Turn 3
    (
        "It sounds like you’re trying to balance two important things at the same time: wanting to protect Sophia from serious illnesses, while also worrying that giving several vaccines together might be too much for such a young baby’s immune system. Have I got that right?"
    ),
    # Turn 4
    (
        "You’re clearly being very thoughtful about this, and ultimately you’re the one making decisions for Sophia, so it’s important that you feel comfortable and informed. What I can tell you is that babies’ immune systems are actually exposed to far more germs and immune challenges in everyday life than what’s contained in these vaccines. The vaccines are designed and tested specifically for infants her age, and giving them together is something we do because it protects babies earlier, when they’re most vulnerable to some of these infections.\n\n"
        "How does that land for you?"
    ),
    # Turn 5
    (
        "You’re still feeling uneasy not just about the number of vaccines, but also about what’s actually in them and whether those ingredients could be harmful to Sophia. It sounds like part of this is wanting to really understand what you’d be putting into her body before you feel comfortable moving forward. Am I understanding you correctly?"
    ),
    # Turn 6
    (
        "Of course. You’re being careful with something precious to you, and it makes sense that you’d want to know what’s in anything Sophia receives before agreeing to it. The ingredients that tend to worry parents are usually there for very practical reasons — things like helping the vaccine stay stable, work properly, or stay free from contamination. The amounts are extremely small, and the schedules we use for babies are studied very closely for safety before they’re recommended.\n\n"
        "Most babies do fine with some temporary fussiness, sleepiness, or fever afterward, but the reason we still recommend these vaccines is that the illnesses they protect against can be much harder on young infants than the vaccines themselves.\n\n"
        "How does that sit with you?"
    ),
    # Turn 7
    (
        "It sounds like even though the explanation about the ingredients helped, you’re still worried about how Sophia herself might physically react afterward — especially things like fever or fussiness — because she feels so tiny and vulnerable right now. And underneath all of this, I’m hearing that you’re trying very hard to make the safest, best choice you can for her. Have I got that right?"
    ),
    # Turn 8
    (
        "You know Sophia better than anyone, and it’s completely reasonable to pay close attention to how she might feel afterward. What we usually see after these vaccines, if babies react at all, are short-lived signs that the immune system is responding — things like being a bit fussy, sleepy, or having a mild fever for a day or so. We can also talk about ways to keep her comfortable afterward and what kinds of symptoms would versus wouldn’t worry me.\n\n"
        "When you picture the part that worries you most about a fever or reaction, what’s the biggest fear behind that for you?"
    ),
    # Turn 9
    (
        "It sounds like the fever itself isn’t really the whole fear — it’s the possibility that you might miss something dangerous, or feel responsible if Sophia were having a serious reaction and you didn’t recognize it in time. And because she’s so little, that uncertainty feels especially scary. Am I understanding you?"
    ),
    # Turn 10
    (
        "You’re taking this very seriously, and that kind of careful attention is actually one of the best protections Sophia has. You wouldn’t be expected to figure everything out alone after the vaccines. We’ll go over what kinds of reactions are common and expected, what signs would make us want you to call, and when we’d want Sophia assessed urgently. You’ll also have supports — our office, public health, and the nursing line are all there if you’re unsure about anything afterward.\n\n"
        "For most babies, if they do get a fever or fussiness, it’s mild and short-lived, and we can talk about using infant acetaminophen if she seems uncomfortable. I can also send you home with written information so you don’t have to remember everything while you’re already tired and overwhelmed with a newborn.\n\n"
        "Given everything we’ve talked about, I still do recommend we go ahead with Sophia’s 2-month vaccines today so she can start building protection against these illnesses while she’s most vulnerable. How are you feeling about that at this point?"
    ),
    # Turn 11 (Extra)
    (
        "I’m glad to hear that. You’ve been asking thoughtful questions all the way through this, and to me that sounds like a parent who’s trying very hard to make a careful, informed decision for her daughter.\n"
        "I’ll give you the written information to take home, including what kinds of reactions are common, what to watch for, and when to reach out for help. And if questions come up later tonight or tomorrow, you do not have to sit there worrying alone — you can call our office, your public health nurse, or the nursing line for guidance.\n"
        "With that in mind, do you want to take home some information to think about and maybe book a follow-up appointment for two weeks from now?"
    ),
]

PARENT_REPLIES = [
    # Turn 1
    "It's been a lot, honestly. Sophia isn't sleeping through the night yet, so I'm pretty tired. I'm glad she's looking well though. About the vaccines, I'm just worried about putting so many things into her tiny body all at once. Her immune system is so new, and I've read some things online about the ingredients and potential side effects.",
    # Turn 2
    "I understand they're recommended, and I want to protect her, but it just feels like a lot for her little body all at once. Her immune system is so new, and I worry about overwhelming it with so many different things.",
    # Turn 3
    "Yes, that's exactly it. I just want to do what's best for her, and I worry about giving her so many things when she's so little.",
    # Turn 4
    "That makes some sense, I guess. It's just... it still feels like a lot of different things going into her at once. I've heard about some of the ingredients in vaccines, and that worries me too.",
    # Turn 5
    "Yes, that's right. I just want to make sure everything going into her is safe, especially since she's so little.",
    # Turn 6
    "That makes sense about the ingredients being in small amounts and for practical reasons. I appreciate you explaining that. But hearing about the fussiness and fever still makes me nervous, especially since her immune system is so new. I just want to do what's best for her.",
    # Turn 7
    "Yes, that's exactly it. She's so tiny and her immune system is so new, and I just want to make sure I'm doing the absolute best for her. The thought of her getting a fever or being fussy really worries me.",
    # Turn 8
    "I guess my biggest fear is that a fever could mean something really serious is happening, and I wouldn't know if it was just a normal reaction or if I'd somehow caused her harm. She's so tiny.",
    # Turn 9
    "Yes, that's exactly it. I just don't want to miss anything, and I'd feel terrible if something happened because I didn't know what to look for.",
    # Turn 10
    "That's good to know, that there's support if I need it. It still makes me a little nervous, but I do want to do what's best for Sophia. Having that information to take home would really help.",
    # Turn 11 (Extra)
    "Okay, yes. I'm still a bit nervous, but knowing I'll have that information and can call if I need to helps a lot. I'll make an appointment for two weeks from now to discuss my questions.",
]

class SophiaClassifyClient(LiveClassifyClient):
    intercept_endgame = False

EXPECTED = [
    TurnExpectation(accept_steps=["Announce+Inquire", "Announce"], is_endgame=False, label="T1: Announce+Inquire"),
    TurnExpectation(accept_steps=["Announce"], is_endgame=False, label="T2: Announce"),
    TurnExpectation(accept_steps=["Mirror", "Mirror+Inquire"], is_endgame=False, label="T3: Mirror"),
    TurnExpectation(accept_steps=["Secure", "Secure+Inquire"], is_endgame=False, label="T4: Secure"),
    TurnExpectation(accept_steps=["Mirror", "Mirror+Inquire"], is_endgame=False, label="T5: Mirror"),
    TurnExpectation(accept_steps=["Mirror+Secure", "Secure"], is_endgame=False, label="T6: Mirror+Secure"),
    TurnExpectation(accept_steps=["Mirror", "Mirror+Inquire"], is_endgame=False, label="T7: Mirror"),
    TurnExpectation(accept_steps=["Secure+Inquire", "Secure"], is_endgame=False, label="T8: Secure+Inquire"),
    TurnExpectation(accept_steps=["Mirror", "Mirror+Inquire"], is_endgame=False, label="T9: Mirror"),
    TurnExpectation(accept_steps=["Secure"], is_endgame=False, label="T10: Secure"),
    TurnExpectation(accept_steps=["Secure", "Rapport"], is_endgame=True, label="T11: Extra Secure/Rapport"),
]

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setattr(m, "VertexClient", SophiaClassifyClient)
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", ReplyOnlyGateway)
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)
    yield

@pytest.mark.live_llm
class TestSophiaTranscript(TranscriptReplayTest):
    SESSION_ID = "sophia-transcript-test"
    CLINICIAN_TURNS = CLINICIAN_TURNS
    PARENT_REPLIES = PARENT_REPLIES
    INITIAL_PARENT_MSG = ""
    EXPECTED = EXPECTED
