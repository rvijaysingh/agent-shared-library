"""Tests for llm/prompt_loader.py.

Uses tmp_path for all template file operations. No live filesystem access
outside of tmp_path.

Five categories:
1. Happy path — load with variables, load with None, multiple placeholders
2. Boundary/edge — no placeholders + empty dict, multiple occurrences of same key
3. Graceful degradation — missing file raises FileNotFoundError
4. Bad input — missing variable key raises KeyError
5. Idempotency/state — loading same file twice gives same result
"""

import pytest

from agent_shared.llm.prompt_loader import PromptLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_template(tmp_path, name: str, content: str) -> str:
    """Write a template file and return the prompts_dir path (as string)."""
    (tmp_path / name).write_text(content, encoding="utf-8")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_load_substitutes_single_variable(tmp_path):
    """load() replaces {name} placeholder with the value from variables."""
    prompts_dir = write_template(tmp_path, "greet.md", "Hello, {name}!")
    loader = PromptLoader(prompts_dir)
    result = loader.load("greet.md", {"name": "Alice"})
    assert result == "Hello, Alice!"


def test_load_substitutes_multiple_variables(tmp_path):
    """load() replaces all {key} placeholders in a multi-variable template."""
    template = "Subject: {subject}\n\nBody:\n{body}\n\nTask name:"
    prompts_dir = write_template(tmp_path, "card_name.md", template)
    loader = PromptLoader(prompts_dir)
    result = loader.load("card_name.md", {"subject": "Q3 Review", "body": "See attached."})
    assert "Q3 Review" in result
    assert "See attached." in result
    assert "{subject}" not in result
    assert "{body}" not in result


def test_load_with_none_variables_returns_raw_content(tmp_path):
    """load() with variables=None returns the template unchanged."""
    template = "Hello, {name}! Your task: {task}"
    prompts_dir = write_template(tmp_path, "raw.md", template)
    loader = PromptLoader(prompts_dir)
    result = loader.load("raw.md", None)
    assert result == template


def test_load_returns_full_file_content(tmp_path):
    """load() returns the complete file content including whitespace."""
    content = "  Leading spaces\n\nBlank lines\n\nTrailing newline\n"
    prompts_dir = write_template(tmp_path, "full.md", content)
    loader = PromptLoader(prompts_dir)
    result = loader.load("full.md", {})
    assert result == content


# ---------------------------------------------------------------------------
# 2. Boundary / edge cases
# ---------------------------------------------------------------------------

def test_load_no_placeholders_with_empty_variables(tmp_path):
    """Template with no placeholders and empty variables dict returns content unchanged."""
    content = "This template has no placeholders at all."
    prompts_dir = write_template(tmp_path, "static.md", content)
    loader = PromptLoader(prompts_dir)
    result = loader.load("static.md", {})
    assert result == content


def test_load_no_placeholders_with_extra_variables(tmp_path):
    """Extra keys in variables that have no matching placeholder are silently ignored."""
    content = "Hello world"
    prompts_dir = write_template(tmp_path, "no_placeholders.md", content)
    loader = PromptLoader(prompts_dir)
    # Extra keys in variables should not cause an error
    result = loader.load("no_placeholders.md", {"unused_key": "ignored"})
    assert result == "Hello world"


def test_load_multiple_occurrences_of_same_placeholder(tmp_path):
    """All occurrences of the same {key} are replaced throughout the template."""
    template = "Name: {name}\nRepeat: {name}\nAgain: {name}"
    prompts_dir = write_template(tmp_path, "repeat.md", template)
    loader = PromptLoader(prompts_dir)
    result = loader.load("repeat.md", {"name": "Bob"})
    assert result == "Name: Bob\nRepeat: Bob\nAgain: Bob"


def test_load_template_with_multiline_content(tmp_path):
    """load() correctly handles multi-line templates with variables."""
    template = "# Prompt\n\nSubject: {subject}\n\n## Body\n\n{body}\n\n---"
    prompts_dir = write_template(tmp_path, "multiline.md", template)
    loader = PromptLoader(prompts_dir)
    result = loader.load("multiline.md", {"subject": "Meeting", "body": "Details here."})
    assert "Meeting" in result
    assert "Details here." in result


# ---------------------------------------------------------------------------
# 3. Graceful degradation
# ---------------------------------------------------------------------------

def test_load_missing_file_raises_file_not_found(tmp_path):
    """load() raises FileNotFoundError when the template file does not exist."""
    loader = PromptLoader(str(tmp_path))
    with pytest.raises(FileNotFoundError, match="nonexistent.md"):
        loader.load("nonexistent.md", {})


def test_load_missing_file_error_message_includes_path(tmp_path):
    """FileNotFoundError message includes the full path to the missing template."""
    loader = PromptLoader(str(tmp_path))
    with pytest.raises(FileNotFoundError) as exc_info:
        loader.load("missing_template.md", {})
    assert "missing_template.md" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Bad input / validation
# ---------------------------------------------------------------------------

def test_load_missing_variable_raises_key_error(tmp_path):
    """load() raises KeyError when a {placeholder} has no matching variable."""
    template = "Hello, {name}! Task: {task}"
    prompts_dir = write_template(tmp_path, "needs_vars.md", template)
    loader = PromptLoader(prompts_dir)
    with pytest.raises(KeyError):
        loader.load("needs_vars.md", {"name": "Alice"})  # missing "task"


def test_load_completely_empty_variables_with_placeholders_raises_key_error(tmp_path):
    """Empty variables dict + template with placeholders raises KeyError."""
    template = "Hello, {name}!"
    prompts_dir = write_template(tmp_path, "with_placeholder.md", template)
    loader = PromptLoader(prompts_dir)
    with pytest.raises(KeyError):
        loader.load("with_placeholder.md", {})


# ---------------------------------------------------------------------------
# 5. Idempotency / state
# ---------------------------------------------------------------------------

def test_load_same_template_twice_returns_same_result(tmp_path):
    """Calling load() twice with the same template and variables returns identical strings."""
    template = "Task: {task}"
    prompts_dir = write_template(tmp_path, "idempotent.md", template)
    loader = PromptLoader(prompts_dir)
    result1 = loader.load("idempotent.md", {"task": "Review PR"})
    result2 = loader.load("idempotent.md", {"task": "Review PR"})
    assert result1 == result2


def test_loader_does_not_cache_between_calls(tmp_path):
    """PromptLoader re-reads the file on each call; modifications are reflected."""
    path = tmp_path / "dynamic.md"
    path.write_text("Version: {v}", encoding="utf-8")
    loader = PromptLoader(str(tmp_path))

    result1 = loader.load("dynamic.md", {"v": "1"})
    # Overwrite the file
    path.write_text("Updated: {v}", encoding="utf-8")
    result2 = loader.load("dynamic.md", {"v": "2"})

    assert result1 == "Version: 1"
    assert result2 == "Updated: 2"


def test_loader_instance_reusable_for_different_templates(tmp_path):
    """A single PromptLoader instance can load different templates from the same dir."""
    write_template(tmp_path, "a.md", "Template A: {val}")
    write_template(tmp_path, "b.md", "Template B: {val}")
    loader = PromptLoader(str(tmp_path))

    result_a = loader.load("a.md", {"val": "alpha"})
    result_b = loader.load("b.md", {"val": "beta"})

    assert result_a == "Template A: alpha"
    assert result_b == "Template B: beta"
