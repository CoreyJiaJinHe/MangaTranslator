import sys
from pathlib import Path

# Add the project root (one level up from 'test') to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from MangaWebTranslator.services.dictionary.jisho import JishoClient


def test_search_jisho():
    """
    Test JishoClient.search_jisho with a sample keyword, print the results, and print cleaned output.
    """
    # Use a common Japanese word for test
    keyword = "日本語"
    results = JishoClient.search_jisho(keyword)
    print("Results for keyword '", keyword, "':\n", results)
    # Optionally, check for expected keys in the result
    assert isinstance(results, dict), "Result should be a dictionary"
    
    
    # Error checking: check 'meta' status
    meta = results.get('meta', {})
    status = meta.get('status')
    if status != 200:
        print(f"Error: Jisho API returned status {status}. Aborting processing.")
        return
    assert 'data' in results, "Result should contain 'data' key"

    def remove_empty(d):
        """
        Recursively remove all empty key-value pairs from dictionaries and lists.
        """
        if isinstance(d, dict):
            return {k: remove_empty(v) for k, v in d.items() if v not in (None, '', [], {}, ()) and remove_empty(v) != {}}
        elif isinstance(d, list):
            return [remove_empty(i) for i in d if i not in (None, '', [], {}, ()) and remove_empty(i) != {}]
        else:
            return d

    cleaned = remove_empty(results)
    print("\nCleaned results (no empty key-value pairs):\n", cleaned)

    # Save cleaned results to a JSON file for readability
    import json
    output_path = Path(__file__).parent / "jisho_cleaned_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"\nCleaned results saved to {output_path}")

    # Separate main translation and examples
    data = cleaned.get('data', [])
    if not data:
        print("No data found in Jisho response.")
        return

    # The first item is the main translation
    main_translation = data[0]
    examples = data[1:] if len(data) > 1 else []

    print("\nMain translation:")
    print(f"Word: {main_translation.get('slug')}")
    print(f"Reading: {main_translation.get('japanese', [{}])[0].get('reading', '')}")
    senses = main_translation.get('senses', [])
    print("Definitions:")
    for sense in senses:
        print(" -", ", ".join(sense.get('english_definitions', [])))

    print("\nExamples:")
    for idx, example in enumerate(examples, 1):
        print(f"Example {idx}:")
        print(f"  Word: {example.get('slug')}")
        print(f"  Reading: {example.get('japanese', [{}])[0].get('reading', '')}")
        senses = example.get('senses', [])
        print("  Definitions:")
        for sense in senses:
            print("   -", ", ".join(sense.get('english_definitions', [])))

if __name__ == "__main__":
    test_search_jisho()
