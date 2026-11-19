# Antonio Nocerino — coaching site

A personal site for Antonio Nocerino, head coach of SSC Napoli Under-19, in the same visual language as Francesco Polverino's career site. It is a separate Next.js app that lives in its own folder, with its own address once published.

## Pages

| Tab | Address | What it holds |
| --- | --- | --- |
| Profile | `/en` | Who he is, the four method chapters, coaching path, playing career, contact |
| Match interpretation | `/en/match-interpretation` | Notes per phase of play, with one match clip per phase |
| Coaching beliefs | `/en/beliefs` | An opening statement and six beliefs |
| Training drills | `/en/training` | Each drill with its training video next to the match video |
| Player identity | `/en/player-identity` | A pitch in his shape; pick a position to read its profile |
| CV | `/en/cv` | One printable page (`Print / save as PDF`) |

Languages: English, Italian, Spanish, Portuguese (European) and French. The language is part of the address (`/it/training`), so a link can be sent in the reader's language. `/` forwards to the visitor's browser language.

## Run locally

```bash
npm install
npm run dev
```

Open [http://localhost:4327](http://localhost:4327).

## Add Antonio's words

All text lives in `src/content`:

- `profile.ts`: Profile tab, coaching path, playing career, contact details, photo
- `coaching.ts`: the four coaching tabs
- `ui.ts`: tab names and small interface labels

In `coaching.ts`, every piece of text that is still `null` shows "Antonio's notes to come" on the page. Replace it with one line per language, always in the order English, Italian, Spanish, Portuguese, French:

```ts
notes: c(
  "English text",
  "Testo italiano",
  "Texto español",
  "Texto português",
  "Texte français",
),
```

When his content is in, set `inPreparation: false` in `profile.ts` to remove the "In preparation" strip from the four tabs.

## Add videos

Every video field in `coaching.ts` that is still `null` shows an empty frame. Replace it with a link:

```ts
trainingVideo: "https://vimeo.com/123456789",        // Vimeo, including unlisted links with a hash
matchVideo: "https://youtu.be/abcdefghijk",           // YouTube
trainingVideo: "/videos/pressing-drill.mp4",         // a file placed in public/videos
```

Vimeo and YouTube players load only after the visitor presses play.

Club footage is confidential by default. Only link clips Antonio and the club are happy to show to whoever can open the site.

## Contact details and photo

In `profile.ts`, fill in `site.contact` (email, phone, LinkedIn, representation). Empty fields stay hidden. For a portrait, put the image in `public/` and set `site.photo` to its path, for example `"/antonio.jpg"`.

## Sources

Coaching dates and roles follow his [Transfermarkt coaching profile](https://www.transfermarkt.it/antonio-nocerino/profil/trainer/76468); the playing career follows his Transfermarkt player profile. Drill names and set-ups, and the 3-4-2-1 shape on the Player identity tab, come from the Napoli Under-19 session plans of September 2026.

## Stack

Next.js (App Router), TypeScript, Tailwind CSS.
