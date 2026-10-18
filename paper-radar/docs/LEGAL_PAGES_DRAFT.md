# About, Privacy and Terms — draft

Status: **draft for review, not legal advice** (2026-10-18). Written from what the code actually
does on `main`. Placeholders are in `[BRACKETS]`.

## Before publishing: things to check

1. **This is not legal advice.** The drafts follow the usual shape for a small, free,
   non-commercial service under UK GDPR, but a privacy notice is a legal document. Get a quick
   read from someone qualified. Your university's information-compliance office often does
   this for free for students.
2. **Your university and funder.** As a PhD student, check two things before promoting
   Atlas beyond your lab:
   - whether your university or funder has rules about side projects and the IP in them;
   - whether lab data in Atlas (papers, notes, comments) is fine to hold on a personal
     service.
3. **ICO data protection fee.** Anyone in the UK who acts as a "controller" of personal
   data may have to pay the ICO's annual fee unless an exemption applies. Atlas holds other
   people's emails and activity, so you'd likely be the controller. The ICO has a short
   self-assessment: <https://ico.org.uk/for-organisations/data-protection-fee/self-assessment/>.
4. **Account deletion.** Atlas has "Leave lab" but no self-serve account deletion. The
   Privacy draft promises deletion **by email request within 30 days**. Either keep that
   promise by hand, or build a delete-account button before you open sign-up wider.
5. **Contact.** `hello@labatlas.app`, forwarded to your inbox by a free forwarder
   (ImprovMX), so no personal address is public. Set it up and send a test before
   publishing.
6. **Accuracy.** If you add a provider (analytics, error tracking, a new AI service), update
   the Privacy page's list in the same PR.

---

## About

Atlas is a shared paper library for research groups. Everyone in a lab adds the papers they
read; Atlas fills in the metadata, merges duplicates and preprints, and keeps the lab's notes
and discussion with each paper. Connected to Claude, it lets Claude answer from the papers a
lab chose to keep.

Atlas is built by Ellen Schrader, a PhD student, as an independent, non-commercial project.
It started as the reading library for the lab Ellen works in. It is not a product of, or
endorsed by, any university, institute or funder.

Atlas is in beta. Things will change and sometimes break. The code is public under the MIT
licence at <https://github.com/ellen-schrader/atlas>, and bug reports and ideas are welcome
as GitHub issues.

Contact: hello@labatlas.app

---

## Privacy

*Last updated: [DATE]*

This page explains what Atlas stores about you, why, where, and who else sees it. Atlas is run
by Ellen Schrader as an individual ("I" below), who is the data controller. Contact:
hello@labatlas.app.

### What Atlas stores

- **Your account:** email address, display name and a password managed by the
  authentication service. Atlas never sees your password in plain text.
- **Your labs:** which labs you belong to and your role in them.
- **What you add and do:**
  - papers you post, and the notes, tags, comments and reactions you write;
  - your bookmarks and reading lists;
  - which papers you have opened;
  - figures you upload.
- **Claude activity:** if your lab turns on Claude access, a log of each request Claude makes
  through Atlas (who, which tool, when and whether it succeeded). Your lab can see this log.
- **In your browser:** your sign-in session, your theme choice and which of your labs is open,
  stored in local storage.
  Atlas uses no advertising or analytics cookies and no tracking.

### Why

Only to run the service: to show your lab its library, keep it tidy, recommend papers from
your own reading, and answer Claude's requests when your lab allows it. The legal basis is
legitimate interest in providing a service you signed up for. Nothing is sold, and nothing is
used for advertising.

### Who can see it

- **Your lab:** members of a lab see that lab's papers, notes, comments and reactions, and
  who posted them. Other labs cannot.
- **Me:** as the person running Atlas, I can access the database to fix problems. I do not
  browse it otherwise.

### Where it is stored, and the services Atlas uses

| Service | What it does for Atlas | What it receives | Location |
|---|---|---|---|
| Supabase | Database, sign-in, file storage | Everything above | EU (Ireland) |
| Fly.io | Runs the Atlas server | Requests as they pass through | UK (London) |
| Vercel | Serves the website | Page requests, IP address | Global network |
| Resend | Sends sign-in and password emails | Your email address | EU (Ireland) |
| Voyage AI | Turns paper text and search queries into embeddings for semantic search | Paper titles and abstracts, search text | USA |
| Anthropic | Generates tags and topic summaries | Paper titles and abstracts | USA |
| Crossref, OpenAlex, arXiv, bioRxiv, doi.org | Look up paper metadata | The DOI or link you added | Various |
| Microsoft Teams | Only if your lab connects a Teams channel | Paper cards posted to that channel; messages posted to Atlas from it | Microsoft |

Paper text sent to Voyage AI and Anthropic is about the paper, not about you. Your notes and
comments are not sent to either for these features.

**When you use Claude with Atlas,** Claude receives the results of your requests: paper
details, tags and lab notes. That happens under your own Claude account and Anthropic's terms
for it, not through Atlas's own Anthropic account.

Where data leaves the UK or EU, these providers use standard contractual safeguards.
[CHECK each provider's data processing terms.]

### How long

For as long as your account exists. You can delete your account yourself in Settings, and your
account details are removed at once. What you posted to a lab (papers, comments, figures, shared
maps) stays with that lab without your name, unless you ask hello@labatlas.app for it to be
removed too. A lab you are the only member of is deleted with your account.

### Your rights

You can ask for a copy of your data, a correction, deletion, or an objection to how it is
used, by emailing hello@labatlas.app. I'll reply within 30 days. If you are unhappy with the
answer, you can complain to the UK Information Commissioner's Office (ico.org.uk).

### Children

Atlas is for researchers and is not intended for anyone under 18.

### Changes

If this page changes in a way that matters, I'll say so in the app.

---

## Terms

*Last updated: [DATE]*

These terms apply when you use Atlas. By creating an account you agree to them.

1. **What Atlas is.** A free, non-commercial beta run by an individual in spare time.
   Features may change, break or be removed, and the service may pause or end. If it ends, I
   will give notice where I can and a way to export your papers.
2. **No warranty.** Atlas is provided "as is", without warranties of any kind. Metadata,
   merges, tags, summaries and anything Claude says using Atlas can be wrong. Check sources
   before relying on them, especially in published work.
3. **Liability.** To the extent the law allows, I am not liable for losses from using or
   being unable to use Atlas, including lost data. Keep your own copies of anything important;
   Atlas can export to BibTeX, RIS, CSV and Markdown. Nothing here limits liability that
   cannot be limited by law.
4. **Your content.** You keep ownership of what you add: notes, comments and uploaded
   figures. You give Atlas permission to store and show it to your lab, and to process it as
   described in the Privacy page. Only upload what you have the right to share, for example
   no copyrighted PDFs or figures you may not reuse.
5. **Acceptable use.** Don't use Atlas to break the law, to harass anyone, to get at another
   lab's data, or to overload or probe the service. Accounts that do may be suspended.
6. **Labs.** Lab owners control membership and Claude access for their lab. Members agree
   that what they post is visible to their lab.
7. **Claude.** Connecting Claude is optional, and your use of Claude is governed by your
   agreement with Anthropic. Atlas is not affiliated with or endorsed by Anthropic.
8. **Law.** These terms are governed by the law of England and Wales.
9. **Contact.** hello@labatlas.app
