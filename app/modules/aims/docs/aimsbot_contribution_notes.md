# AIMSBot Contribution Notes

These notes are for drafting a personal contribution to the academic paper and the companion website report. They are based on the project discussion and the rough report draft, but they are not a rewrite of the report itself.

## Core contribution theme

My contribution focused on translating a relational communication framework into software that could support realistic practice, stay consistent across turns, and remain usable when model output was imperfect.

The main design choice was a hybrid system:
- use the LLM for nuance, phrasing, and flexible interpretation
- use deterministic code for scoring, state transitions, fallback behavior, and guardrails

That split mattered because the tool had to be reliable enough for training, not just fluent enough to sound good.

## What was hardest

### 1. Turning theory into executable behavior

AIMS is a human communication framework, but the software had to express it as concrete steps, state changes, and scoring rules. That meant deciding how to map qualitative ideas like announcing, inquiring, mirroring, and securing into behavior the system could enforce consistently.

### 2. Balancing flexibility and control

The model needed enough freedom to produce believable responses, but not enough freedom to drift away from the intended training purpose. The key tradeoff was letting the system feel conversational while still keeping it aligned with the AIMS workflow.

### 3. Managing state across turns

The bot had to remember what had already happened in the conversation: what had been said, what concerns had been surfaced, what had been mirrored, and what still needed to happen. That made session state and history management a central part of the design, not a background detail.

### 4. Handling imperfect model output

The system had to keep working when the model was slow, inconsistent, or returned malformed output. That required fallback logic and post-processing so a bad model response did not break the user experience.

### 5. Keeping the experience usable

The design was not just about AI behavior. It also had to be understandable, responsive, and low-friction for learners. A good training tool has to guide the user without becoming noisy or distracting.

## What was most interesting

### 1. The bot is a teaching system, not just a chatbot

The most interesting part was that the software is doing pedagogy. It is not only generating text; it is trying to shape how someone practices a difficult conversation.

### 2. The architecture separates policy from generation

One of the strongest design choices was to keep the policy in code and use the model as one component inside a controlled pipeline. That made the system easier to reason about, easier to test, and better suited to a training environment.

### 3. The interaction model had to feel human but remain bounded

The simulated patient needed to feel realistic enough to support practice, but the conversation still had to stay within a structured training framework. That tension between realism and structure was one of the most interesting design problems.

### 4. The work sat between AI and user experience

A lot of the engineering choices were really experience choices:
- when to coach
- how much to explain
- how much friction to introduce
- what to prioritize in the interface

The technical work was inseparable from the learning experience.

## Points to emphasize in the academic paper

- AIMSBot was designed as a hybrid system that combines LLM flexibility with deterministic guardrails.
- The main challenge was translating a qualitative communication framework into a stateful, testable system.
- Reliability mattered as much as generation quality because the tool is meant for practice and training.
- The implementation required balancing conversational realism, pedagogical clarity, and safety.
- State management, fallback behavior, and scoring logic were central to making the system usable.
- The project is interesting because it sits at the intersection of AI, health communication, and educational design.

## Points to emphasize in the website report

- The system was built to help people practice difficult health conversations in a realistic but controlled setting.
- The design prioritized clarity, reliability, and ease of use.
- AIMSBot was intentionally built to support repeated practice and feedback, not just one-off answers.
- Some features were deferred so the core experience could remain dependable.
- The project reflects a deliberate balance between innovation and restraint.

## A short contribution statement

My contribution centered on the technical and experiential design of the system. I focused on how to turn a communication framework into a tool that could actually support learning in practice. That required balancing flexibility and control, realism and reliability, and feature richness and usability.

## A slightly fuller version for the paper

One of the main challenges in AIMSBot was translating a relational communication framework into software behavior that could be executed consistently. The system needed to support realistic conversation while still staying aligned with the AIMS approach, so the design used a hybrid architecture: the language model handled nuance, while code enforced the rules, scoring, and fallback behavior. That made the system more reliable for training, but it also required careful decisions about state, timing, and how much freedom to give the model. In practice, the most important work was not just generating responses, but building a tool that could support learning, preserve conversational continuity, and remain usable when model output was imperfect.

## A slightly fuller version for the website report

AIMSBot was designed to help people practice difficult health conversations in a realistic but controlled way. The goal was not just to make the system sound conversational, but to make it useful for learning. To do that, the design balanced flexibility with structure: the model could support natural dialogue, but the underlying system kept the conversation aligned with the AIMS framework and provided consistent feedback. Some features were intentionally left for later versions so the first release could stay clear, dependable, and easy to use.
