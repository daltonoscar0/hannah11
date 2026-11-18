#!/usr/bin/env python3
"""Build the Hannah 11 experiments from the Hannah 10 PCIbex downloads.

Usage:
    python3 build_hannah11.py Hannah10_*.zip            # or unpacked folders
    python3 build_hannah11.py --out hannah11 --duration 25 <inputs...>

Each input is one Hannah 10 experiment as downloaded from the PCIbex Farm
(a .zip archive or the unpacked folder). For every input the script writes a
folder and a .zip under --out holding the same files with these changes:

  1. Two 30-second breaks, placed 1/3 and 2/3 of the way through the
     training + test trials. Key presses do nothing during a break; when it
     ends the usual "press any key to continue" screen appears.
  2. SC experiments: the test block now runs before the training block.
     IQ experiments keep their block order (pass --swap-iq to swap them too).
  3. The item, answer-key and wording fixes listed in ITEM_FIXES, TEXT_FIXES
     and HTML_FIXES below.

Stimuli are never retyped: every edit is a search and replace on the original
text, and anything that cannot be found is reported instead of guessed at.
The run ends with a report (also saved as hannah11_report.txt) that lists
every change made and every change that could not be applied.
"""

import argparse
import datetime
import io
import os
import re
import sys
import zipfile

SCRIPT_NAME = "iqversionMTurk.js"
BREAK_SECONDS = 30
YES, NO = 0, 1  # index into as: [["f", YES], ["j", NO]]

# --------------------------------------------------------------------------
# Fix tables
# --------------------------------------------------------------------------

# Each entry locates an item by a fragment of its sentence, then edits the
# sentence, the question and/or the answer key of that item only.
#   sentence : fragment that identifies the item
#   s_old/s_new : optional replacement inside the sentence
#   q_old/q_new : optional replacement of the question text (the
#                 "According to the sentence you just read," prefix is kept)
#   key      : optional new value for hasCorrect
ITEM_FIXES = [
    dict(label="p6 (practice)",
         sentence="boat sails are to be lashed down by two deck hands",
         q_old="in a storm, is the boat wind-propelled?",
         q_new="should the sails be left loose during a storm?",
         why="A sailboat is wind-propelled by category; the new question is "
             "answered by the sentence. Key stays NO."),
    dict(label="SC_ambig_training 3",
         sentence="troops attacked by the terrorists had mounted a counter offensive",
         s_old="had mounted a counter offensive",
         s_new="had called for reinforcements",
         why="A counter offensive is an attack on the terrorists, which made "
             "YES defensible. Question and key (NO) are unchanged."),
    dict(label="filler_training 104",
         sentence="The girl apologized to her parents for having stayed out past curfew",
         q_old="was the girl caught staying out late?",
         q_new="did the girl stay out past curfew?",
         why="Being caught is not entailed. Key stays YES."),
    dict(label="filler_training 107",
         sentence="Bikes were not permitted on the town's sidewalks",
         q_old="did people bike on the sidewalks?",
         q_new="were bikes permitted on the town's sidewalks?",
         key=NO,
         why="A rule does not entail behavior and the key differed between "
             "versions. New question is entailed; key is NO everywhere."),
    dict(label="SC_unamb 32 / IQ_unamb 32",
         sentence="city_council who was hired by the mayor",
         s_old="city_council who was hired by the mayor",
         s_new="city_council that was overseen by the mayor",
         q_old="was the mayor hired by someone?",
         q_new="was the mayor overseen by someone?",
         why="'who' for a council, and a mayor hiring a council is "
             "implausible. Key stays NO. Note: item 31 still uses 'hired'."),
    dict(label="SC_unamb 40 / IQ_unamb 40",
         sentence="puppy who was carried by the assistant",
         s_old="puppy who was carried",
         s_new="puppy that was carried",
         why="'who' for a non-human."),
    dict(label="filler_test 50",
         sentence="When the driver eventually overtook the last truck",
         s_old="inside lane",
         s_new="right lane",
         q_old="did the driver overtake all the trucks?",
         q_new="did the driver overtake the last truck?",
         why="'All the trucks' was an inference; 'inside lane' is British "
             "usage. Key stays YES."),
    dict(label="filler_test 61",
         sentence="The impatient brother immediately took the toy away from his younger sister",
         q_old="did the brother like to share?",
         q_new="did the brother give the toy to his younger sister?",
         why="The old question asked about a disposition. Key stays NO."),
    dict(label="filler_test 67",
         sentence="Judy sank into the luxurious seat, enjoying the smell of leather",
         q_old="was the seat made of leather?",
         q_new="did Judy enjoy the smell of leather?",
         why="The smell need not come from the seat. Key stays YES."),
    dict(label="filler_training 85",
         sentence="Foreigners unfailingly fall in love with the place",
         s_old="with the place",
         s_new="with Paris",
         q_old="did foreigners like the place?",
         q_new="do foreigners like Paris?",
         why="'The place' had no antecedent and the tenses did not match. "
             "Key stays YES."),
    dict(label="filler_training 92",
         sentence="The doctor mistook the symptoms for food poisoning",
         q_old="did the patient have food poisoning?",
         q_new="was the doctor right about the symptoms?",
         why="'The patient' is never introduced. Key stays NO."),
    dict(label="filler_training 94",
         sentence="A different kind of fire arose within Andrew as he thought about the new idea",
         q_old="was Andrew passionate about the idea?",
         q_new="did Andrew think about the new idea?",
         why="The old question required interpreting a metaphor. Key stays YES."),
    dict(label="filler_training 98",
         sentence="The arrogant man added the woman's contact information to his phone",
         q_old="did the man get the woman's phone number?",
         q_new="did the man add the woman's contact information to his phone?",
         why="Contact information is not necessarily a phone number. Key stays YES."),
]

# Plain text replacements applied to the whole script.
TEXT_FIXES = [
    dict(label="filler_training 79 typo",
         old="putting the children bed", new="putting the children to bed"),
    dict(label="filler_test 65 spelling",
         old="good bye", new="goodbye"),
]

# Replacements in the HTML resources. {duration} is filled from --duration.
HTML_FIXES = [
    dict(file="intro1.html", label="intro1 'the the'",
         old="press of the the space bar", new="press of the space bar"),
    dict(file="intro2.html", label="intro2 breaks",
         old="You can take breaks as you need them, but please try to do so "
             "before you've started reading a new item, when the screen just "
             "shows dashes.",
         new="The experiment includes two scheduled 30-second breaks, and it "
             "will tell you when each one begins. Please save your rest for "
             "those breaks. If you do need to pause at another time, please "
             "do so before you've started reading a new item, when the "
             "screen just shows dashes."),
    dict(file="consent.html", label="consent duration",
         old="an approximately 15 min research study",
         new="an approximately {duration} min research study"),
    dict(file="consent.html", label="consent 'with no penalty'",
         old="at any time no penalty", new="at any time with no penalty"),
    dict(file="consent.html", label="consent stray parenthesis",
         old="18 years of age or older.)", new="18 years of age or older."),
    dict(file="newfile.html", label="newfile 'the data'",
         old="greater understanding of data",
         new="greater understanding of the data"),
]

# --------------------------------------------------------------------------
# Code inserted into the experiment script
# --------------------------------------------------------------------------

WITH_BREAKS_JS = """\
// Inserts one break after each equal share of the trials: with two breaks
// they fall 1/3 and 2/3 of the way through.
function WithBreaks(main, breaks) {
    this.args = [main].concat(breaks);
    this.run = function(arrays) {
        var trials = arrays[0];
        var nBreaks = arrays.length - 1;
        var out = [];
        var next = 1;
        for (var i = 0; i < trials.length; ++i) {
            if (next <= nBreaks && i == Math.round(next * trials.length / (nBreaks + 1))) {
                for (var j = 0; j < arrays[next].length; ++j)
                    out.push(arrays[next][j]);
                ++next;
            }
            out.push(trials[i]);
        }
        return out;
    };
}
function withBreaks(main) {
    return new WithBreaks(main, Array.prototype.slice.call(arguments, 1));
}

"""


def break_item(n, total):
    html = (
        "<div style='text-align: center; max-width: 36em; margin: 0 auto;'>"
        "<p><b>Break %d of %d</b></p>"
        "<p>Please rest for %d seconds. The experiment will continue on its "
        "own when the time is up, and you will then be asked to press a key "
        "to go on.</p>"
        "<div style='width: 300px; height: 10px; border: 1px solid #888; "
        "margin: 1.5em auto;'>"
        "<div style='height: 100%%; background: #888; "
        "animation: breakTimer %ds linear forwards;'></div></div>"
        "<style>@keyframes breakTimer { from { width: 100%%; } "
        "to { width: 0; } }</style>"
        "</div>"
    ) % (n, total, BREAK_SECONDS, BREAK_SECONDS)
    return '    ["break%d", "Message", {html: "%s", transfer: %d}],' % (
        n, html, BREAK_SECONDS * 1000)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.lines = []
        self.problems = 0

    def head(self, text):
        self.lines.append("")
        self.lines.append(text)
        self.lines.append("=" * len(text))

    def ok(self, text):
        self.lines.append("  [done]    " + text)

    def skip(self, text):
        self.lines.append("  [n/a]     " + text)

    def bad(self, text):
        self.problems += 1
        self.lines.append("  [MISSING] " + text)

    def note(self, text):
        self.lines.append("  [note]    " + text)

    def text(self):
        return "\n".join(self.lines) + "\n"


def loose(text):
    """Regex for text that tolerates whitespace and apostrophe differences."""
    parts = []
    for token in text.split():
        token = re.escape(token)
        token = token.replace("'", "['’]")
        parts.append(token)
    return r"\s+".join(parts)


def match_case(new, old):
    if old[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def active_lines(js):
    """Yield (start, end, is_active) for each line; commented lines are inactive."""
    pos, in_block = 0, False
    for line in js.splitlines(True):
        stripped = line.strip()
        active = not in_block and not stripped.startswith("//")
        if in_block:
            if "*/" in line:
                in_block = False
        elif stripped.startswith("/*"):
            active = False
            if "*/" not in line:
                in_block = True
        yield pos, pos + len(line), active
        pos += len(line)


def is_active(js, index):
    for start, end, active in active_lines(js):
        if start <= index < end:
            return active
    return False


def sub_active(js, pattern, repl):
    """re.subn restricted to lines that are not commented out."""
    out, count = [], 0
    for start, end, active in active_lines(js):
        line = js[start:end]
        if active:
            line, n = re.subn(pattern, repl, line)
            count += n
        out.append(line)
    return "".join(out), count


def count_active(js, pattern):
    return sum(len(re.findall(pattern, js[a:b]))
               for a, b, active in active_lines(js) if active)


def load_input(path):
    """Return {relative path: bytes} for a .zip archive or a folder."""
    files = {}
    if os.path.isdir(path):
        for root, _dirs, names in os.walk(path):
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                with open(full, "rb") as handle:
                    files[rel] = handle.read()
    elif os.path.isfile(path) and not zipfile.is_zipfile(path):
        with open(path, "rb") as handle:
            files[SCRIPT_NAME] = handle.read()
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.replace("\\", "/")
                parts = [p for p in rel.split("/") if p not in ("", ".")]
                if ".." in parts or rel.startswith("/"):
                    raise SystemExit("Unsafe path in %s: %s" % (path, rel))
                files["/".join(parts)] = archive.read(info)
    else:
        raise SystemExit("Not a folder or .zip archive: %s" % path)
    return files


def find_file(files, basename):
    hits = [p for p in files if p.split("/")[-1] == basename]
    return hits[0] if len(hits) == 1 else None


# --------------------------------------------------------------------------
# Script transformation
# --------------------------------------------------------------------------

SEQ_LINE = re.compile(r"^[ \t]*var\s+shuffleSequence\s*=.*$", re.M)


def split_blocks(line):
    """Split the active shuffleSequence line around its two trial blocks.

    Returns (before, [block expressions], after), where the blocks are the
    arguments that follow "i3" inside the innermost seq(...).
    """
    anchor = re.search(r'"i3"\s*,\s*', line)
    if not anchor:
        raise ValueError('no "i3" entry in shuffleSequence')
    start = anchor.end()
    depth, quote, args, arg_start, i = 0, None, [], start, start
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                args.append(line[arg_start:i].strip())
                return line[:start], args, line[i:]
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(line[arg_start:i].strip())
            arg_start = i + 1
        i += 1
    raise ValueError("unbalanced parentheses in shuffleSequence")


def transform_sequence(js, report, swap_iq):
    lines = [m for m in SEQ_LINE.finditer(js)]
    if len(lines) != 1:
        raise ValueError("expected one active shuffleSequence line, found %d"
                         % len(lines))
    m = lines[0]
    old_line = m.group(0)
    before, blocks, after = split_blocks(old_line)
    if len(blocks) != 2:
        raise ValueError("expected a training block and a test block after "
                         '"i3", found %d blocks' % len(blocks))
    train, test = blocks
    kind = "SC" if "SC_ambig" in test else "IQ" if "IQ_ambig" in test else None
    if kind is None:
        raise ValueError("test block names neither SC_ambig nor IQ_ambig: %s"
                         % test)
    training = "RCtrain" if "_ambig_training" in train else "FillerTrain"

    swap = kind == "SC" or swap_iq
    first, second = (test, train) if swap else (train, test)
    new_line = '%swithBreaks(seq(%s, %s), "break1", "break2")%s' % (
        before, first, second, after)
    replacement = (WITH_BREAKS_JS
                   + "// Hannah 10: " + old_line.strip() + "\n"
                   + new_line)
    js = js[:m.start()] + replacement + js[m.end():]

    report.ok("breaks: two %d-second breaks at 1/3 and 2/3 of the "
              "training + test trials" % BREAK_SECONDS)
    if swap:
        report.ok("block order: test block now runs before the training block")
    else:
        report.skip("block order: unchanged for IQ (training, then test)")
    report.note("training block: " + train)
    report.note("test block:     " + test)
    return js, kind, training, train, test


def insert_break_items(js, report):
    items = break_item(1, 2) + "\n" + break_item(2, 2) + "\n"
    sep = re.search(r'\[\s*"sep"\s*,\s*"Separator"\s*,\s*\{\s*\}\s*\]\s*,[ \t]*\n',
                    js)
    if sep:
        at = sep.end()
    else:
        start = re.search(r"var\s+items\s*=\s*\[[ \t]*\n", js)
        if not start:
            raise ValueError("could not find the items array")
        at = start.end()
    report.ok("break items: break1 and break2 added to the items array")
    return js[:at] + items + js[at:]


def apply_item_fix(js, fix, report):
    hits = [m for m in re.finditer(loose(fix["sentence"]), js)
            if is_active(js, m.start())]
    if not hits:
        return js, False
    for m in reversed(hits):
        tail = re.compile(r"hasCorrect\s*:\s*(\d)").search(js, m.end(),
                                                           m.end() + 900)
        end = tail.end() if tail else min(len(js), m.end() + 900)
        chunk = js[m.start():end]
        done = []
        if "q_old" in fix:
            q = re.search(loose(fix["q_old"]), chunk, re.I)
            if q:
                new_q = match_case(fix["q_new"], q.group(0))
                chunk = chunk[:q.start()] + new_q + chunk[q.end():]
                done.append('question "%s" -> "%s"' % (q.group(0), new_q))
            else:
                report.bad('%s: sentence found, but not the question "%s"'
                           % (fix["label"], fix["q_old"]))
        if "s_old" in fix:
            s = re.search(loose(fix["s_old"]), chunk)
            if s:
                chunk = chunk[:s.start()] + fix["s_new"] + chunk[s.end():]
                done.append('sentence "%s" -> "%s"' % (s.group(0), fix["s_new"]))
            else:
                report.bad('%s: sentence found, but not "%s"'
                           % (fix["label"], fix["s_old"]))
        if "key" in fix:
            k = re.search(r"(hasCorrect\s*:\s*)(\d)", chunk)
            if k and int(k.group(2)) != fix["key"]:
                chunk = chunk[:k.start(2)] + str(fix["key"]) + chunk[k.end(2):]
                done.append("key %s -> %s" % (
                    ["YES", "NO"][int(k.group(2))], ["YES", "NO"][fix["key"]]))
            elif k:
                done.append("key already %s" % ["YES", "NO"][fix["key"]])
            else:
                report.bad("%s: no hasCorrect found to set" % fix["label"])
        js = js[:m.start()] + chunk + js[end:]
        if done:
            report.ok("%s: %s" % (fix["label"], "; ".join(done)))
            report.note("  reason: " + fix["why"])
    return js, True


def transform_script(js, report, opts):
    js, kind, training, train, test = transform_sequence(js, report, opts.swap_iq)
    js = insert_break_items(js, report)

    groups = {}
    for start, end, active in active_lines(js):
        if active:
            for name, num in re.findall(r'\[\[\s*"(\w+)"\s*,\s*(\d+)\s*\]',
                                        js[start:end]):
                groups.setdefault(name, set()).add(num)
    used = {}
    for name in re.findall(r'"(\w+)"', train + " " + test):
        label = re.sub(r"_(ambig|unamb)$", "", name)
        used.setdefault(label, set()).update(groups.get(name, set()))
    total = sum(len(v) for v in used.values())
    report.note("trials per participant: %d (%s); breaks after trial %d and %d"
                % (total,
                   ", ".join("%s %d" % (k, len(v)) for k, v in sorted(used.items())),
                   round(total / 3.0), round(2 * total / 3.0)))

    for fix in ITEM_FIXES:
        js, found = apply_item_fix(js, fix, report)
        if not found:
            report.skip("%s: item not in this experiment" % fix["label"])

    for fix in TEXT_FIXES:
        pattern = loose(fix["old"])
        js, n = sub_active(js, pattern, fix["new"])
        if n:
            report.ok('%s: "%s" -> "%s" (%d place%s)' % (
                fix["label"], fix["old"], fix["new"], n, "" if n == 1 else "s"))
        else:
            report.skip('%s: "%s" not in this experiment' % (
                fix["label"], fix["old"]))

    js, n = sub_active(js, r'(\bq\s*:\s*"(?:[^"\\\n]|\\.)*?)[ \t]+"', r'\1"')
    if n:
        report.ok("trailing spaces removed from %d question string%s"
                  % (n, "" if n == 1 else "s"))
    else:
        report.skip("no question strings with trailing spaces")

    lead = r'(\bs\s*:\s*")[ \t]+'
    n_lead = count_active(js, lead)
    if n_lead and opts.trim_leading_space:
        js, _ = sub_active(js, lead, r"\1")
        report.ok("leading space removed from %d sentence strings" % n_lead)
    elif n_lead:
        report.note("%d sentence strings start with a space, which "
                    "DashedSentence shows as an empty first region. Left "
                    "as is; pass --trim-leading-space to remove it "
                    "(shifts word positions for those items)." % n_lead)

    if count_active(js, r'\bs\s*:\s*"[^"\n]*[A-Za-z]_[A-Za-z]'):
        report.note("underscore-joined tokens left unchanged; check in the "
                    "preview that they display as two words in one region.")
    return js, kind, training


def transform_html(files, report, opts):
    if not any(p.endswith(".html") for p in files):
        report.note("no HTML files supplied with this input: the consent, "
                    "intro and debrief wording fixes were not applied.")
        return
    for fix in HTML_FIXES:
        path = find_file(files, fix["file"])
        if path is None:
            report.bad("%s: %s not found in the download" % (
                fix["label"], fix["file"]))
            continue
        text = files[path].decode("utf-8")
        new = fix["new"].format(duration=opts.duration)
        text, n = re.subn(loose(fix["old"]), lambda _m: new, text)
        if n:
            files[path] = text.encode("utf-8")
            report.ok("%s: now reads \"%s\"" % (fix["label"], new))
        else:
            report.bad('%s: "%s" not found in %s' % (
                fix["label"], fix["old"], fix["file"]))


def build_one(path, opts, report):
    files = load_input(path)
    script = find_file(files, SCRIPT_NAME)
    if script is None:
        candidates = [p for p in files
                      if p.endswith(".js") and b"shuffleSequence" in files[p]
                      and b"var items" in files[p]]
        if len(candidates) != 1:
            raise ValueError("could not identify the experiment script")
        script = candidates[0]

    raw = files[script].decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    js = raw.replace("\r\n", "\n")

    name_probe = SEQ_LINE.search(js)
    if not name_probe:
        raise ValueError("no active shuffleSequence line")
    report.head("%s" % os.path.basename(path.rstrip("/")))
    js, kind, training = transform_script(js, report, opts)
    files[script] = js.replace("\n", newline).encode("utf-8")
    transform_html(files, report, opts)

    name = "Hannah11_%s_%s%s" % (kind, training, opts.date)
    out_dir = os.path.join(opts.out, name)
    for rel, data in files.items():
        dest = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(data)
    with zipfile.ZipFile(out_dir + ".zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for rel, data in sorted(files.items()):
            archive.writestr(rel, data)
    report.note("written to %s (and %s.zip)" % (out_dir, name))
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the Hannah 11 experiments from Hannah 10 downloads.")
    parser.add_argument("inputs", nargs="+",
                        help="Hannah 10 downloads (.zip or unpacked folder)")
    parser.add_argument("--out", default="hannah11",
                        help="output folder (default: hannah11)")
    parser.add_argument("--duration", type=int, default=25,
                        help="minutes stated on the consent form (default: 25)")
    parser.add_argument("--swap-iq", action="store_true",
                        help="also run test before training in IQ experiments")
    parser.add_argument("--trim-leading-space", action="store_true",
                        help="remove the leading space from sentence strings")
    parser.add_argument("--date",
                        default=datetime.date.today().strftime("%Y%m%d"),
                        help="date suffix for the output names")
    opts = parser.parse_args(argv)

    os.makedirs(opts.out, exist_ok=True)
    report = Report()
    names, failed = [], 0
    for path in opts.inputs:
        try:
            names.append(build_one(path, opts, report))
        except (ValueError, UnicodeDecodeError) as error:
            failed += 1
            report.head(os.path.basename(path.rstrip("/")))
            report.bad("NOT BUILT: %s" % error)

    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        report.head("Warnings")
        report.bad("two inputs produced the same output name: %s"
                   % ", ".join(dupes))

    report.head("Summary")
    report.note("%d built, %d failed, %d change%s could not be applied"
                % (len(names), failed, report.problems - failed,
                   "" if report.problems - failed == 1 else "s"))
    text = report.text()
    with io.open(os.path.join(opts.out, "hannah11_report.txt"), "w",
                 encoding="utf-8") as handle:
        handle.write(text)
    sys.stdout.write(text)
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
