"""Training hub curriculum: modules of lessons, each tied to a guide, with a short quiz.

Quiz answers stay on the server; clients get questions and options only.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import LessonProgress

PASS_SCORE = 0.67


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    answer: int
    explanation: str


class Lesson(BaseModel):
    id: str
    title: str
    guide_id: str
    key_points: list[str]
    practice: str | None = Field(default=None, description="sim task id or 'walkaround'")
    quiz: list[QuizQuestion]


class Module(BaseModel):
    id: str
    title: str
    lessons: list[Lesson]


def _q(question: str, options: list[str], answer: int, explanation: str) -> QuizQuestion:
    return QuizQuestion(question=question, options=options, answer=answer, explanation=explanation)


CURRICULUM: list[Module] = [
    Module(
        id="safety-basics",
        title="Safety basics",
        lessons=[
            Lesson(
                id="seatbelt",
                title="Seatbelt and cab safety",
                guide_id="seatbelt-and-cab-safety",
                key_points=[
                    "Buckle up before you start the engine.",
                    "Keep it on the whole time the engine runs, even for short moves.",
                    "Climb in and out with three points of contact. Never jump.",
                ],
                quiz=[
                    _q(
                        "When should you fasten your seatbelt?",
                        ["After the first task", "Before starting the engine", "Only on slopes"],
                        1,
                        "Buckle up before the engine starts, every time.",
                    ),
                    _q(
                        "You need to move the machine 5 metres. The seatbelt should be:",
                        ["Fastened", "Optional for short moves", "Unbuckled to get out fast"],
                        0,
                        "Keep it fastened the whole time the engine is running.",
                    ),
                    _q(
                        "How do you get down from the cab?",
                        ["Jump clear", "Face the machine, three points of contact", "Slide down"],
                        1,
                        "Face the machine and keep three points of contact.",
                    ),
                ],
            ),
            Lesson(
                id="walkaround",
                title="Pre-start walkaround",
                guide_id="pre-start-walkaround",
                practice="walkaround",
                key_points=[
                    "Walk the machine in one direction so you don't miss a side.",
                    "Fresh puddles under the machine point to a leak.",
                    "Never check for a hydraulic leak with your hand.",
                ],
                quiz=[
                    _q(
                        "How should you check a hose you think is leaking?",
                        [
                            "Run your hand along it",
                            "Look for wet streaks, never touch",
                            "Squeeze it",
                        ],
                        1,
                        "Pressurized fluid can pierce skin. Look, don't touch.",
                    ),
                    _q(
                        "You find a damaged part during the walkaround. What next?",
                        ["Operate carefully", "Tag out and tell your supervisor", "Fix it later"],
                        1,
                        "Don't operate until it's cleared. Tag out and report it.",
                    ),
                    _q(
                        "Why walk around in one direction?",
                        ["It's faster", "So you don't skip a side", "It's tradition"],
                        1,
                        "One direction means every side gets checked.",
                    ),
                ],
            ),
            Lesson(
                id="soft-ground",
                title="Soft ground, slopes, and edges",
                guide_id="soft-ground-and-edges",
                key_points=[
                    "If a track sinks or the machine leans: stop, keep the bucket low, back out.",
                    "Keep well back from edges, trench walls, and ramp crests.",
                    "Travel straight up and down slopes, not across them.",
                ],
                quiz=[
                    _q(
                        "Your right track starts to sink near the ramp edge. First step?",
                        ["Raise the bucket", "Stop travelling and digging", "Speed up"],
                        1,
                        "Stop first, keep the bucket low, then back out onto firm ground.",
                    ),
                    _q(
                        "How should you drive on a slope?",
                        ["Across it", "Straight up and down", "Zig-zag"],
                        1,
                        "Travel straight up and down, bucket low.",
                    ),
                    _q(
                        "After rain, ground that was firm yesterday is:",
                        ["Still firm", "Worth re-checking", "Safer"],
                        1,
                        "Rain changes the ground. Re-check it.",
                    ),
                ],
            ),
        ],
    ),
    Module(
        id="operating-skills",
        title="Operating skills",
        lessons=[
            Lesson(
                id="joystick",
                title="Joystick controls and digging",
                guide_id="excavator-operation",
                practice="dig",
                key_points=[
                    "ISO pattern: left stick moves the stick and swing, right stick boom and bucket.",
                    "Small, smooth movements give better control than full-lever jerks.",
                    "Check the swing area before every swing.",
                ],
                quiz=[
                    _q(
                        "In the ISO pattern, pushing the right joystick forward:",
                        ["Raises the boom", "Lowers the boom", "Swings left"],
                        1,
                        "Right stick forward lowers the boom.",
                    ),
                    _q(
                        "Which gives better bucket control?",
                        ["Full-lever jerks", "Small, smooth movements", "Only one lever at a time"],
                        1,
                        "Smooth, combined movements control better and use less fuel.",
                    ),
                    _q(
                        "Before swinging, you should:",
                        ["Check the swing area is clear", "Sound the horn only", "Raise the boom"],
                        0,
                        "Always check for people and the counterweight's tail swing.",
                    ),
                ],
            ),
            Lesson(
                id="loading",
                title="Loading haul trucks",
                guide_id="loading-trucks",
                practice="reach",
                key_points=[
                    "Wait for the truck to stop and the driver to signal.",
                    "Never pass the bucket over the truck cab.",
                    "Load evenly and don't overload.",
                ],
                quiz=[
                    _q(
                        "When can you start loading a truck?",
                        [
                            "As it reverses in",
                            "When it has stopped and the driver signals",
                            "Anytime",
                        ],
                        1,
                        "Wait for the stop and the driver's signal.",
                    ),
                    _q(
                        "The bucket should never pass over:",
                        ["The truck body", "The truck cab", "The ground"],
                        1,
                        "Never swing a load over the cab.",
                    ),
                    _q(
                        "Where does the first pass go?",
                        ["Toward the front of the body", "Over the tailgate", "Anywhere"],
                        0,
                        "Start toward the front and spread the load to centre it.",
                    ),
                ],
            ),
            Lesson(
                id="idle-fuel",
                title="Idle time and fuel",
                guide_id="idle-and-fuel",
                practice="grade",
                key_points=[
                    "Waiting more than a few minutes? Idle down, or shut off if site rules allow.",
                    "Tell dispatch when you're waiting so work can be reshuffled.",
                    "Keep dig and dump close together to cut swing and travel.",
                ],
                quiz=[
                    _q(
                        "A truck is 10 minutes late. You should:",
                        [
                            "Keep the engine at full throttle",
                            "Idle down and tell dispatch",
                            "Leave",
                        ],
                        1,
                        "Idle down and let dispatch reshuffle the work.",
                    ),
                    _q(
                        "Long idling mainly:",
                        [
                            "Burns fuel without moving material",
                            "Warms the hydraulics",
                            "Is required",
                        ],
                        0,
                        "Idle burns fuel and engine hours for nothing.",
                    ),
                    _q(
                        "Worn bucket teeth make every pass:",
                        ["Easier", "Harder and thirstier", "No different"],
                        1,
                        "Keep teeth and cutting edge in good condition.",
                    ),
                ],
            ),
        ],
    ),
    Module(
        id="wellbeing",
        title="Fatigue and emergencies",
        lessons=[
            Lesson(
                id="fatigue",
                title="Fatigue and breaks",
                guide_id="fatigue-and-breaks",
                key_points=[
                    "Slower, uneven cycles and more pauses are early fatigue signs.",
                    "Tell your supervisor if you feel drowsy. It's always OK to stop.",
                    "Don't use the end of the shift to catch up.",
                ],
                quiz=[
                    _q(
                        "Your cycles are slowing late in the shift. That may be:",
                        ["Fatigue", "Normal, push on", "A fuel problem"],
                        0,
                        "Slowing cycles are a classic fatigue sign.",
                    ),
                    _q(
                        "You feel drowsy. What do you do?",
                        [
                            "Open a window and continue",
                            "Park safely and tell your supervisor",
                            "Speed up to finish",
                        ],
                        1,
                        "Park safely, take a break, tell your supervisor.",
                    ),
                    _q(
                        "Behind schedule at the end of the shift, you should:",
                        ["Rush to catch up", "Keep a safe pace", "Skip checks"],
                        1,
                        "Rushing when tired is when incidents happen.",
                    ),
                ],
            ),
            Lesson(
                id="emergencies",
                title="Emergencies and reporting",
                guide_id="emergencies-and-reporting",
                key_points=[
                    "Stop safely, lower the attachment, call your supervisor.",
                    "Report every near miss, even if nobody was hurt.",
                    "Use the voice button: what, where, anyone hurt, what you did.",
                ],
                quiz=[
                    _q(
                        "A near miss where nobody was hurt should be:",
                        ["Ignored", "Reported", "Mentioned at the next meeting"],
                        1,
                        "Near-miss reports prevent the next accident.",
                    ),
                    _q(
                        "After contact with a power line, if there's no fire you should:",
                        ["Jump out", "Stay in the cab and warn others away", "Keep working"],
                        1,
                        "Stay in the cab if it's safe and call the supervisor.",
                    ),
                    _q(
                        "First step in any emergency:",
                        ["Stop the machine safely", "Take a photo", "Finish the task"],
                        0,
                        "Stop safely, lower the attachment, engage the lockout.",
                    ),
                ],
            ),
        ],
    ),
]

LESSONS: dict[str, Lesson] = {lesson.id: lesson for m in CURRICULUM for lesson in m.lessons}


class QuizResult(BaseModel):
    lesson_id: str
    score: float
    passed: bool
    correct: list[bool]
    explanations: list[str]


def grade(lesson: Lesson, answers: list[int]) -> QuizResult:
    if len(answers) != len(lesson.quiz):
        raise ValueError(f"expected {len(lesson.quiz)} answers, got {len(answers)}")
    correct = [a == q.answer for a, q in zip(answers, lesson.quiz)]
    score = round(sum(correct) / len(correct), 2)
    return QuizResult(
        lesson_id=lesson.id,
        score=score,
        passed=score >= PASS_SCORE,
        correct=correct,
        explanations=[q.explanation for q in lesson.quiz],
    )


def record_result(db: Session, operator_id: int, activity_id: str, score: float) -> LessonProgress:
    """Store a quiz, simulator, or walkaround result. Activity ids: lesson id, 'sim:<task>',
    or 'walkaround:<scenario>'."""
    row = LessonProgress(operator_id=operator_id, lesson_id=activity_id, quiz_score=score)
    db.add(row)
    db.commit()
    return row


def best_scores(db: Session, operator_id: int) -> dict[str, float]:
    best: dict[str, float] = {}
    for row in db.scalars(select(LessonProgress).where(LessonProgress.operator_id == operator_id)):
        if row.quiz_score is not None:
            best[row.lesson_id] = max(best.get(row.lesson_id, 0.0), row.quiz_score)
    return best
