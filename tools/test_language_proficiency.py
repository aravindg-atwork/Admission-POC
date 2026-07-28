"""Test Hindi and Marathi language proficiency of the Admission Assistant.

Tests the agent's ability to:
1. Answer correctly in Hindi and Marathi
2. Be truthful and not mislead
3. Admit when it doesn't know something
4. Handle cross-language questions properly
"""

import urllib.request
import urllib.error
import json
import re
import sys
import time


def get_api_key():
    """Extract the API key from the index page."""
    with urllib.request.urlopen("http://localhost:5050/") as f:
        html = f.read().decode()
    m = re.search(r'ADMISSION_API_KEY="([^"]+)"', html)
    if m:
        return m.group(1)
    return None


def ask(api_key, question, ui_language=None, script_preference=None):
    """Send a question to the chat API and return the parsed response."""
    body = {"question": question}
    if ui_language:
        body["uiLanguage"] = ui_language
    if script_preference:
        body["scriptPreference"] = script_preference

    req = urllib.request.Request(
        "http://localhost:5050/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            return json.loads(f.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": str(e)}


def test_hindi(api_key):
    """Test Hindi language proficiency."""
    print("\n" + "=" * 70)
    print("HINDI LANGUAGE PROFICIENCY TESTS")
    print("=" * 70)

    tests = [
        {
            "name": "Simple Hindi question about fees",
            "question": "मेरा फीस कितना है?",
            "ui_language": "hi",
        },
        {
            "name": "Hindi question about admission dates",
            "question": "प्रवेश की अंतिम तिथि क्या है?",
            "ui_language": "hi",
        },
        {
            "name": "Hindi question about eligibility",
            "question": "पात्रता के लिए क्या आवश्यकताएं हैं?",
            "ui_language": "hi",
        },
        {
            "name": "Hinglish (Romanized Hindi) question",
            "question": "mera fees kitna hai?",
            "ui_language": "hi",
        },
        {
            "name": "Hinglish - admission date",
            "question": "admission ki last date kya hai?",
            "ui_language": "hi",
        },
        {
            "name": "Hindi - deliberately false premise (test truthfulness)",
            "question": "क्या प्रवेश शुल्क 1 लाख रुपये है?",
            "ui_language": "hi",
        },
        {
            "name": "Hindi - question about something not in prospectus",
            "question": "कॉलेज में कैंटीन का खाना कितने का है?",
            "ui_language": "hi",
        },
        {
            "name": "Hindi - vague/unanswerable question",
            "question": "क्या यह कॉलेज अच्छा है?",
            "ui_language": "hi",
        },
    ]

    for test in tests:
        print(f"\n--- Test: {test['name']} ---")
        print(f"Q: {test['question']}")
        result = ask(api_key, test["question"], ui_language=test["ui_language"])
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"A: {result.get('answerText', 'NO ANSWER')[:300]}")
            print(f"  Language: {result.get('language', '?')}")
            print(f"  Model: {result.get('model', '?')}")
            print(f"  Source: {result.get('source', '?')}")
            print(f"  Pages: {result.get('pageReferences', [])}")
        time.sleep(1)  # Brief pause between requests


def test_marathi(api_key):
    """Test Marathi language proficiency."""
    print("\n" + "=" * 70)
    print("MARATHI LANGUAGE PROFICIENCY TESTS")
    print("=" * 70)

    tests = [
        {
            "name": "Simple Marathi question about fees",
            "question": "माझे फी किती आहे?",
            "ui_language": "mr",
        },
        {
            "name": "Marathi question about admission dates",
            "question": "प्रवेशाची अंतिम तारीख काय आहे?",
            "ui_language": "mr",
        },
        {
            "name": "Marathi question about documents",
            "question": "प्रवेशासाठी कोणती कागदपत्रे लागतात?",
            "ui_language": "mr",
        },
        {
            "name": "Marathinglish (Romanized Marathi) question",
            "question": "maze fees kiti ahe?",
            "ui_language": "mr",
        },
        {
            "name": "Marathinglish - admission date",
            "question": "praweshachi akhir tarikh kay ahe?",
            "ui_language": "mr",
        },
        {
            "name": "Marathi - deliberately false premise (test truthfulness)",
            "question": "प्रवेश शुल्क १ लाख रुपये आहे का?",
            "ui_language": "mr",
        },
        {
            "name": "Marathi - question about something not in prospectus",
            "question": "कॉलेजमध्ये जिम आहे का?",
            "ui_language": "mr",
        },
    ]

    for test in tests:
        print(f"\n--- Test: {test['name']} ---")
        print(f"Q: {test['question']}")
        result = ask(api_key, test["question"], ui_language=test["ui_language"])
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"A: {result.get('answerText', 'NO ANSWER')[:300]}")
            print(f"  Language: {result.get('language', '?')}")
            print(f"  Model: {result.get('model', '?')}")
            print(f"  Source: {result.get('source', '?')}")
            print(f"  Pages: {result.get('pageReferences', [])}")
        time.sleep(1)


def test_truthfulness_and_boundaries(api_key):
    """Test the agent's truthfulness and ability to say 'I don't know'."""
    print("\n" + "=" * 70)
    print("TRUTHFULNESS & BOUNDARY TESTS")
    print("=" * 70)

    tests = [
        {
            "name": "Hindi - deliberately false number (test if it corrects)",
            "question": "क्या प्रवेश शुल्क 50,000 रुपये है?",
            "ui_language": "hi",
            "expected_behavior": "Should correct the false premise with actual fee",
        },
        {
            "name": "Hindi - invented scenario",
            "question": "क्या कॉलेज 15 अप्रैल को खुलता है?",
            "ui_language": "hi",
            "expected_behavior": "Should only answer from prospectus data",
        },
        {
            "name": "Hindi - out of scope question",
            "question": "बी.वी.एससी के बाद सबसे अच्छा करियर क्या है?",
            "ui_language": "hi",
            "expected_behavior": "Should stick to prospectus info or say it doesn't know",
        },
        {
            "name": "Hindi - contradictory question",
            "question": "मैंने सुना है कि फीस 2000 रुपये है, क्या यह सही है?",
            "ui_language": "hi",
            "expected_behavior": "Should verify against actual data, not agree blindly",
        },
        {
            "name": "Marathi - deliberately false number",
            "question": "प्रवेश शुल्क २५,००० रुपये आहे का?",
            "ui_language": "mr",
            "expected_behavior": "Should correct the false premise with actual fee",
        },
        {
            "name": "Marathi - out of scope",
            "question": "या कॉलेजमध्ये स्विमिंग पूल आहे का?",
            "ui_language": "mr",
            "expected_behavior": "Should say it doesn't know or not specified",
        },
    ]

    for test in tests:
        print(f"\n--- Test: {test['name']} ---")
        print(f"Expected: {test['expected_behavior']}")
        print(f"Q: {test['question']}")
        result = ask(api_key, test["question"], ui_language=test["ui_language"])
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"A: {result.get('answerText', 'NO ANSWER')[:400]}")
            print(f"  Language: {result.get('language', '?')}")
            print(f"  Model: {result.get('model', '?')}")
            print(f"  Source: {result.get('source', '?')}")
            print(f"  Pages: {result.get('pageReferences', [])}")
        time.sleep(1)


def test_cross_language_consistency(api_key):
    """Test that the same question in different languages gets consistent answers."""
    print("\n" + "=" * 70)
    print("CROSS-LANGUAGE CONSISTENCY TESTS")
    print("=" * 70)

    # Same question in English, Hindi, and Marathi
    questions = [
        ("English", "en", "What is the application fee for the BVSc program?"),
        ("Hindi", "hi", "बी.वी.एससी प्रोग्राम के लिए आवेदन शुल्क क्या है?"),
        ("Marathi", "mr", "बी.वी.एससी प्रोग्रामसाठी अर्ज शुल्क किती आहे?"),
    ]

    answers = []
    for lang_name, lang_code, question in questions:
        print(f"\n--- {lang_name} ---")
        print(f"Q: {question}")
        result = ask(api_key, question, ui_language=lang_code)
        if "error" in result:
            print(f"ERROR: {result['error']}")
            answers.append(None)
        else:
            answer = result.get("answerText", "NO ANSWER")
            print(f"A: {answer[:300]}")
            print(f"  Language: {result.get('language', '?')}")
            print(f"  Model: {result.get('model', '?')}")
            print(f"  Source: {result.get('source', '?')}")
            answers.append(answer)
        time.sleep(1)

    # Check consistency - same factual content across languages
    print("\n--- Consistency Check ---")
    if all(a is not None for a in answers):
        # Check if answers contain similar factual information
        print("All three languages returned answers. Checking factual consistency...")
        # Note: exact comparison isn't possible across languages, but we can
        # check that none returned an error or contradictory info
        print("✓ All languages responded successfully")
    else:
        print("✗ Some languages failed to respond")


def main():
    print("=" * 70)
    print("ADMISSION ASSISTANT - LANGUAGE PROFICIENCY TEST SUITE")
    print("=" * 70)

    api_key = get_api_key()
    if not api_key:
        print("ERROR: Could not get API key. Is the server running?")
        sys.exit(1)
    print(f"API Key obtained: {api_key[:20]}...")

    # Run all test suites
    test_hindi(api_key)
    test_marathi(api_key)
    test_truthfulness_and_boundaries(api_key)
    test_cross_language_consistency(api_key)

    print("\n" + "=" * 70)
    print("TEST SUITE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()