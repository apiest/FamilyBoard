/* FamilyBoard event theme matcher.
 *
 * Maps a free-form event title to a theme key that picks a monochrome
 * line-art SVG under /familyboard/icons/events/<theme>.svg. The card
 * tints that SVG via CSS mask so it blends with the member color.
 *
 * Returns `null` when no keyword matches — by design. The card then
 * skips the decoration and renders a plain colored tile.
 *
 * Per-event escape hatches via the description:
 *   [FB:theme=<key>]   force a specific theme
 *   [FB:theme=none]    suppress decoration for this event
 */

// Single source of truth: theme key -> list of lowercase keyword
// tokens. Tokens are matched as whole words after diacritics are
// stripped from the title and the title is split on non-word chars.
// Insertion order matters: themes listed first win on ties, so
// `birthday` (above `party`) catches "verjaardag" before `party` could.
export const EVENT_THEME_KEYWORDS = {
  birthday: [
    "verjaardag", "jarig", "bday", "birthday", "trouwdag", "jubileum",
    "anniversary",
  ],
  beer: [
    "bier", "biertje", "kroeg", "cafe", "pub", "bros", "hos",
  ],
  party: [
    "party", "feest", "feestje", "borrel", "drinks", "viering",
    "celebration", "etentje",
  ],
  school: [
    "school", "schooldag", "huiswerk", "homework", "toets", "exam",
    "tentamen", "studie", "study", "les", "lesson", "klas", "class",
    "college", "lecture", "rapport",
  ],
  phone: [
    "bellen", "belafspraak", "telefonisch", "telefoon", "call", "phone",
  ],
  work: [
    "werk", "work", "kantoor", "office", "vergadering", "meeting",
    "overleg", "deadline", "standup", "stand-up", "demo", "presentatie",
    "presentation", "interview",
  ],
  badminton: [
    "badminton", "shuttle", "racket",
  ],
  fishing: [
    "vissen", "vis", "viscursus", "hengel", "vissport",
  ],
  walking: [
    "wandelen", "wandeling", "wandel", "wandeldoos", "wandeldozen",
    "stroll", "walk",
  ],
  hiking: [
    "hike", "hiking", "trektocht", "trekking", "sponsorloop",
    "sponsorhike", "avondvierdaagse", "vierdaagse", "daagse",
  ],
  outdoors: [
    "scouting", "padvinders", "kamp", "natuur", "bos",
  ],
  gym: [
    "gym", "sport", "sporten", "fitness", "training", "trainen",
    "workout", "hardlopen", "running", "run", "rennen", "fietsen",
    "bike", "cycling", "zwemmen", "swim", "swimming", "voetbal",
    "football", "soccer", "tennis", "yoga", "pilates",
  ],
  doctor: [
    "dokter", "doctor", "huisarts", "tandarts", "dentist", "ziekenhuis",
    "hospital", "kliniek", "clinic", "afspraak", "appointment",
    "controle", "checkup", "check-up", "fysio", "physio", "apotheek",
    "pharmacy", "medicatie", "medication", "intake",
  ],
  bbq: [
    "bbq", "barbecue", "barbeque", "grillen", "grill",
  ],
  food: [
    "eten", "diner", "dinner", "lunch", "ontbijt", "breakfast", "brunch",
    "koffie", "coffee", "thee", "tea", "restaurant", "snack", "afhalen",
    "takeaway", "take-out", "kookles", "cooking",
  ],
  camping: [
    "camping", "kamperen", "tent", "caravan",
  ],
  travel: [
    "vakantie", "vacation", "holiday", "reis", "trip", "vlucht",
    "flight", "vliegen", "vliegtuig", "trein", "train", "auto", "car",
    "rijden", "weekend", "uitje", "outing",
  ],
  family: [
    "familie", "family", "ouders", "parents", "oma", "opa", "grandma",
    "grandpa", "tante", "oom", "uncle", "aunt", "playdate",
    "speelafspraak", "kinderen",
  ],
  friends: [
    "dames", "meiden", "vriendinnen", "vrienden", "friends",
    "girls", "ladies",
  ],
  shopping: [
    "boodschappen", "groceries", "shop", "shopping", "winkelen",
    "winkel", "supermarkt", "supermarket", "ah", "jumbo", "lidl",
    "aldi", "albert", "bestellen", "order",
  ],
  cleaning: [
    "schoonmaken", "cleaning", "poetsen", "stofzuigen", "vacuum",
    "wassen", "laundry", "wasmachine", "tuin", "garden", "tuinieren",
    "gardening", "klussen", "chores", "opruimen",
  ],
  pet: [
    "hond", "dog", "kat", "cat", "huisdier", "pet", "dierenarts", "vet",
    "uitlaten",
  ],
  music: [
    "muziek", "music", "concert", "festival", "gig", "band", "koor",
    "choir", "pianoles", "drumles", "gitaarles", "movie", "film",
    "bioscoop", "cinema", "theater", "theatre", "show",
  ],
};

// Sentinel used in [FB:theme=...] markers to suppress decoration.
export const EVENT_THEME_NONE = "none";

const _OVERRIDE_RE = /\[FB:theme=([a-z0-9_-]+)\]/i;

function _stripDiacritics(s) {
  try {
    return s.normalize("NFD").replace(/\p{M}/gu, "");
  } catch (_) {
    return s;
  }
}

function _tokenize(title) {
  return _stripDiacritics(String(title || "").toLowerCase())
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

const _TOKEN_INDEX = (() => {
  const idx = new Map();
  for (const [theme, words] of Object.entries(EVENT_THEME_KEYWORDS)) {
    for (const w of words) {
      const first = _tokenize(w)[0];
      if (first && !idx.has(first)) idx.set(first, theme);
    }
  }
  return idx;
})();

/**
 * Pick a theme key for an event.
 *
 * @param {string} title Event title / summary.
 * @param {string} [description] Optional event description; scanned for
 *   a `[FB:theme=<key>]` override marker. `[FB:theme=none]` suppresses
 *   the decoration for that event.
 * @returns {string|null} Theme key, or `null` when nothing matches and
 *   no override is set. Callers must skip decoration on null.
 */
export function eventTheme(title, description) {
  if (description) {
    const m = _OVERRIDE_RE.exec(description);
    if (m) {
      const key = m[1].toLowerCase();
      if (key === EVENT_THEME_NONE) return null;
      if (key in EVENT_THEME_KEYWORDS) return key;
    }
  }
  for (const tok of _tokenize(title)) {
    const t = _TOKEN_INDEX.get(tok);
    if (t) return t;
  }
  return null;
}

if (typeof window !== "undefined") {
  window.FamilyBoardEventTheme = {
    eventTheme,
    EVENT_THEME_KEYWORDS,
    EVENT_THEME_NONE,
  };
}
