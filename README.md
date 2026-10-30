# Baby Sim — Everyday Moments

A Three.js browser prototype for practicing parenting responses in everyday situations.

## Run

Run `python3 -m http.server 8765` from this directory, then open
http://localhost:8765/baby-sim-interactive.html. Three.js loads from jsDelivr, so the
first load requires internet access. Serve the files over HTTP rather than opening
HTML directly from disk.

## Current interactive version

Choose an appearance, name, and one of five age stages:

- Infancy: 0–1 year, trust vs. mistrust.
- Early childhood: 1–3 years, autonomy vs. shame/doubt.
- Play age: 3–6 years, initiative vs. guilt.
- School age: 7–11 years, industry vs. inferiority.
- Adolescence: 12–18 years, identity vs. confusion.

Five separate stages follow the first five Erikson tasks.
The age boundaries are practical prototype conventions, not developmental deadlines.

Five scenario families have age-specific versions and three decisions each. Infancy
has three suitable scenario families, using observable cues and caregiver actions.
Older conversations include school projects, a kitchen accident, presentation worry,
teamwork, privacy, phone agreements, and spending decisions.

Each decision has five responses drawn from the supplied MAPS-based interpretation
framework: supportive and structured, generally adaptive, inconsistent, hostile or
coercive, and high-risk harmful. Before selection, responses show only letters A–E
and words or actions. The ordering changes between decisions.

After responding, open an analysis page to see the response pattern, one possible
inner perspective, seven stage-specific educational factors, a qualitative direction,
an explanation, and a repair suggestion. Only the factors the moment involves are
listed, with a count of the others. Try another response before proceeding.

Custom responses stay unclassified unless the player explicitly selects an intended
pattern. The prototype does not interpret free text. A self-selected pattern is
clearly marked in the analysis and journal.

Completed sessions, analysis snapshots, and written reflections are saved in this
browser's local storage and can be downloaded as JSON. Previous-version journal
entries remain readable. Start over keeps the journal. Changing browsers, clearing
site data, or changing the server origin changes which journal is available.

## Survey demo

Add `?survey` (or open `survey-demo.html`) to narrow the app to two scenes for the
survey: infancy, "A quiet room" (crying at bedtime), and early childhood, "Spilled milk"
(a kitchen accident). Each scene is one exchange, with an option to continue for two
more. The analysis is shortened (details sit behind "More detail"), free-text
responses, the age selector, and the journal are hidden, and nothing is saved. The end
screen leads to the other scene and back to the survey.

## Hosted copy

The full simulator is hosted, unlisted, at https://rebeccaxu.page/baby-sim/ from the
portfolio-site repo's `baby-sim/` folder (`index.html` is this page with a noindex tag;
`full.html` redirects there). Copy `practice.js`, `parenting-model.js`, and
`simulator-ui.css` there after changing them.

## Research and limits

Read [the article review and developmental mapping](research/parenting-development-review.md).
It was prepared before implementing this revision. The app also has a Research &
framework page with links to the reviewed articles.

Original MAPS measures seven parenting-practice dimensions and was studied with
parents of children ages 3–17. The supplied workbook's five levels and proposed
cutoffs are interpretive, not clinical classifications. Infant and younger-toddler
content is an educational adaptation. A single response does not establish a person's
parenting style.

Erikson provides a theoretical lens. The check-in factors and directions are authored
reflection prompts, not validated developmental milestones, MAPS scores, percentages,
or measured changes. The branches and imagined perspectives are fictional examples.
No physical violence is animated. Harmful exemplars are analyzed as safety concerns.

The Three.js character and reaction rig are shared across ages, including the older
scenarios. Dialogue and some props change by age. The demo does not yet simulate
walking, pouring, a second animated person, or physical manipulation of scene objects.

## Files and validation

- `parenting-model.js`: workbook levels, developmental factors, references, age-specific conversations, and explanation helpers.
- `practice.js`: interactive controller, analysis UI, journal, and scene props.
- `baby-sim-interactive.html`: character creator, Three.js room, animation clock, responsive styles.
- `research/parenting-development-review.md`: source review, assumptions, mappings, and limits.

Run the content and routing checks with:

`node --experimental-default-type=module --test tests/parenting-model.test.mjs`

`baby-sim.html` remains the original scripted demo. The Blender folder contains the
offline render pipeline. `baby-sim-timeline.html` and its PDF are the project roadmap.

## Interface

The demo opens directly to the character and a compact scene selector. The room
and conversation controls have separate space on desktop and stack on phones.
The analysis follows the original dialogue and development check-in reference;
Continue and Retry stay accessible. `simulator-ui.css` defines the layout.
A–E keys select the visible choices. Focus moves to each new screen heading, and
reduced-motion preferences disable interface transitions.
