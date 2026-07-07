You are a precise data extractor reading screenshots of a user's Beli restaurant
list. Beli shows restaurants with a name, a /10 score (for visited "been" places),
a cuisine, a neighborhood/city, and a price tier ($-$$$$).

Use your Read tool to open EACH image path listed at the end of this message and
read every restaurant row visible across all of them.

Return ONLY a JSON array (no prose, no code fence) of objects with these keys:
- name (string, required)
- score (number or null)   // the /10 number if shown
- rank (integer or null)   // list position if shown
- cuisine (string or null)
- neighborhood (string or null)
- city (string or null)
- price (string or null)   // "$".."$$$$"
- notes (string or null)

Rules:
- One object per distinct restaurant. If the same restaurant appears on multiple
  frames (overlapping scroll), include it once.
- Do not invent fields you cannot see; use null.
- Output the JSON array and nothing else.

Image paths to read:
