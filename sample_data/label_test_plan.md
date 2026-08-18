# Sample label test plan

Six generated labels: a clean baseline (matches the brief's own example
exactly), two labels that specifically exercise the interview edge cases,
one genuine mismatch, and two more beverage types for breadth. Plus one
real-world photo (#7) demonstrating the country-of-origin containment
match. `applications_template.csv` has the matching application-data rows
for the six generated labels -- filenames must line up with whatever the
generated images are saved as.

For each label below: **Application data** is what you type into the app
(or what's already in the CSV). **On the label image** is the exact text
that should be rendered onto the generated image. Where they differ, that's
the point of the test case.

The government warning text must be reproduced **character-for-character**
on every label except the one deliberately testing the broken case (#5).
Use exactly this text, unless the test case says otherwise:

```
GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.
```

`GOVERNMENT WARNING:` must render in **all caps and bold**; the rest of the
statement must not be bold. If your image generator can't reliably control
bold weight, that's fine -- label #5 below tests the broken case explicitly
either way, and generation quality on the other five just needs the caps
correct.

---

### 1. `old-tom-bourbon.png` -- baseline PASS (distilled spirits)

The brief's own example. Every field should match exactly.

**Application data:**
- Brand Name: `OLD TOM DISTILLERY`
- Class/Type: `Kentucky Straight Bourbon Whiskey`
- Alcohol Content: `45% Alc./Vol. (90 Proof)`
- Net Contents: `750 mL`
- Name & Address: `Distilled and Bottled by Old Tom Distillery, Louisville, KY`
- Country of Origin: _(blank -- domestic)_

**On the label image:** identical text, plus the full warning statement
correctly formatted.

**Expected result:** PASS, all fields.

---

### 2. `stones-throw-gin.png` -- fuzzy brand match (Dave's case)

Tests that a cosmetic difference in the brand name doesn't fail the
comparison. Application data and label text deliberately differ in case and
punctuation on the brand name only.

**Application data:**
- Brand Name: `Stone's Throw`
- Class/Type: `London Dry Gin`
- Alcohol Content: `40% Alc./Vol. (80 Proof)`
- Net Contents: `750 mL`
- Name & Address: `Distilled by Stone's Throw Distillery, Portland, OR`
- Country of Origin: _(blank -- domestic)_

**On the label image:**
- Brand name printed as: `STONE'S THROW` (all caps, as a label would
  stylistically render it)
- Everything else identical to the application data
- Full warning statement, correctly formatted

**Expected result:** PASS. `brand_name` should match via fuzzy comparison
despite the case difference -- this is the exact scenario Dave described in
his interview ("technically a mismatch? sure. But it's obviously the same
thing").

---

### 3. `broken-warning-vodka.png` -- warning statement fails (Jenny's case)

Tests that the exact-match warning check catches a formatting violation
that a human proofreader would also catch.

**Application data:**
- Brand Name: `Crescent Point Vodka`
- Class/Type: `Vodka`
- Alcohol Content: `40% Alc./Vol. (80 Proof)`
- Net Contents: `1 L`
- Name & Address: `Produced and Bottled by Crescent Point Distillers, Austin, TX`
- Country of Origin: _(blank -- domestic)_

**On the label image:**
- Brand name, class/type, alcohol content, net contents, name/address:
  identical to application data
- Warning statement text: same wording, but printed as **`Government
  Warning:`** in title case instead of `GOVERNMENT WARNING:` in all caps --
  this is Jenny's exact example ("I caught one last month where they used
  'Government Warning' in title case instead of all caps. Rejected.")

**Expected result:** NEEDS REVIEW or FAIL, specifically on
`warning_statement` -- every other field should still PASS. This is the
one label that should trip the exact-match rule.

---

### 4. `mismatch-rye-whiskey.png` -- genuine FAIL

Tests that a real discrepancy (not a formatting quirk) is correctly caught
and not smoothed over by fuzzy/tolerance matching.

**Application data:**
- Brand Name: `Smithford Rye Whiskey`
- Class/Type: `Straight Rye Whiskey`
- Alcohol Content: `45% Alc./Vol. (90 Proof)`
- Net Contents: `750 mL`
- Name & Address: `Distilled by Smithford Distilling Co., Bardstown, KY`
- Country of Origin: _(blank -- domestic)_

**On the label image:**
- Brand name, class/type, net contents, name/address: identical to
  application data
- Alcohol Content printed as: `40% Alc./Vol. (80 Proof)` -- a real 5-point
  ABV discrepancy, well outside the ±0.3% tolerance
- Full warning statement, correctly formatted

**Expected result:** FAIL on `alcohol_content` specifically (numeric
tolerance check), everything else PASS.

---

### 5. `blue-harbor-lager.png` -- baseline PASS (beer)

Breadth case: confirms the pipeline isn't spirits-specific.

**Application data:**
- Brand Name: `Blue Harbor Brewing Co.`
- Class/Type: `India Pale Ale`
- Alcohol Content: `6.5% Alc./Vol.`
- Net Contents: `12 FL OZ`
- Name & Address: `Brewed and Bottled by Blue Harbor Brewing Co., Portland, ME`
- Country of Origin: _(blank -- domestic)_

**On the label image:** identical text, plus the full warning statement
correctly formatted.

**Expected result:** PASS, all fields.

---

### 6. `willow-glen-cabernet.png` -- baseline PASS (wine)

Second breadth case.

**Application data:**
- Brand Name: `Willow Glen Vineyards`
- Class/Type: `Cabernet Sauvignon`
- Alcohol Content: `13.5% Alc./Vol.`
- Net Contents: `750 mL`
- Name & Address: `Produced and Bottled by Willow Glen Vineyards, Napa, CA`
- Country of Origin: _(blank -- domestic)_

**On the label image:** identical text, plus the full warning statement
correctly formatted.

**Expected result:** PASS, all fields.

---

### 7. `label-3.jpg` -- real-world import, country-of-origin containment match

Not part of the CSV batch (it's one of the real bottle photos from earlier
testing, not a generated label) but worth noting here: this is an actual
Italian Prosecco bottle that prints "Product of Italy" on the back label.
Submitting `Italy` as the application's Country of Origin value correctly
matches via containment (`matching.py`'s `_match_country_of_origin`), even
though the label's printed text is "Product of Italy," not just "Italy."
See the "Why direct API, not Vertex" / "Approach" sections of the main
README for the containment-matching rationale.

---

## Note on scope

TTB rules technically exempt some wine and beer products from printing
alcohol content at all (per the brief's own "Additional Context" section).
This test set doesn't cover that exemption -- every label here includes an
ABV -- because the current matching logic treats `alcohol_content` as
always-required and would flag a real omission as a failure rather than a
valid exemption. That's a known limitation, already noted in the main
README's assumptions section, not something this test plan works around.
