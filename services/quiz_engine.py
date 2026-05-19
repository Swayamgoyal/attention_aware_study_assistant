"""
SVC-04 · Quiz Engine Agent
Port: 8004 | Question generator, evaluator & scorer

Uses the unified LLM provider for quiz generation and semantic answer evaluation.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from services.llm_provider import get_llm

load_dotenv()


class QuizEngine:
    """Generates quiz questions and evaluates answers using LLM."""

    def __init__(self):
        self.llm = get_llm()

    def generate_quiz(self, topic: str, difficulty: int = 2) -> dict:
        q_type = "MCQ" if difficulty <= 2 else "open-ended short answer"

        system_prompt = f"""You are a quiz generator. Generate a single {q_type} question about: {topic}
Difficulty level: {difficulty}/5

You MUST respond with ONLY valid JSON (no markdown, no extra text):
{{
  "question": "The quiz question text",
  "type": "{'mcq' if difficulty <= 2 else 'open_ended'}",
  "options": {"[\"A) ...\", \"B) ...\", \"C) ...\", \"D) ...\"]" if difficulty <= 2 else "null"},
  "correct_answer": "The correct answer",
  "explanation": "Brief explanation of why this is correct"
}}"""

        result = self.llm.generate_json(system_prompt, f"Generate a quiz question about: {topic}")

        required = {"question", "type", "correct_answer", "explanation"}
        if not required.issubset(result.keys()):
            raise ValueError(f"Missing keys: {required - result.keys()}")

        return result

    def evaluate_answer(self, question: str, correct_answer: str,
                        learner_answer: str) -> dict:
        system_prompt = """You are an answer evaluator. Compare the learner's answer to the correct answer.
Evaluate semantic correctness, not exact wording. Be encouraging but honest.

Respond with ONLY valid JSON:
{
  "score": 0.0 to 1.0,
  "is_correct": true or false,
  "feedback": "Constructive feedback string"
}"""

        user_msg = f"Question: {question}\nCorrect Answer: {correct_answer}\nLearner's Answer: {learner_answer}"
        result = self.llm.generate_json(system_prompt, user_msg, max_tokens=256)

        result["score"] = max(0.0, min(1.0, float(result.get("score", 0))))
        result["is_correct"] = bool(result.get("is_correct", False))
        return result


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("=" * 60)
    print("  SVC-04 · Quiz Engine — Self-Test")
    print("=" * 60)

    engine = QuizEngine()
    print(f"\nLLM: {engine.llm.get_info()}")

    if not engine.llm.is_available():
        print("\n⚠️  No LLM configured. Cannot run quiz tests.")
    else:
        print("\n📝 Generating MCQ (difficulty=2)...")
        quiz = engine.generate_quiz("What is photosynthesis?", difficulty=2)
        print(f"   Q: {quiz['question']}")
        if quiz.get("options"):
            for opt in quiz["options"]:
                print(f"      {opt}")

        print("\n📝 Generating open-ended (difficulty=4)...")
        quiz2 = engine.generate_quiz("Explain backpropagation", difficulty=4)
        print(f"   Q: {quiz2['question']}")

        print("\n✏️  Evaluating answer...")
        ev = engine.evaluate_answer(
            "What is photosynthesis?",
            "Plants convert sunlight into energy",
            "Plants use sunlight to make food",
        )
        print(f"   Score: {ev['score']} | Correct: {ev['is_correct']}")
        print(f"   Feedback: {ev['feedback']}")

    print("\n" + "=" * 60)
    print("  Quiz engine tests complete! ✓")
    print("=" * 60)