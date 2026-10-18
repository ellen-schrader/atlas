# Delete my account — plan (PR C)

Status: **built on branch `account-deletion`, awaiting review** (2026-10-18). Decisions below were made by Ellen; all four follow the recommendations. Follows the landing page PRs (#152, #154). The
Privacy page currently says deletion is by email to hello@labatlas.app; this PR makes it a button.

Cost: **$0/month**. One migration, one SQL function and a Settings panel. No new services.

## What happens today if an auth user is deleted

| Effect | Why |
|---|---|
| **Deletion fails** for anyone who ever made a topic map | `maps.created_by` is `NOT NULL` with no `ON DELETE` (`20260713170000_maps.sql:14`) |
| Their **comments and figure comments vanish** from lab discussions, with the mentions inside them | `comments.author_id`, `figure_comments.author_id` cascade |
| A lab whose only owner leaves is **left with no owner**; nobody can manage members or Claude access | "≥1 owner" is checked only inside the RPCs, not on cascade |
| Their **figures stay but nobody can edit or delete them** | figures RLS is `uploaded_by = auth.uid()`, which becomes NULL |
| Posts stay, attributed to nobody | `paper_posts.posted_by` is `SET NULL` |
| Sessions, OAuth grants and connector consents go | `auth.*` cascades; the connector gate rejects revoked sessions at once |

## Proposed behaviour (recommended defaults; see Decisions)

When someone deletes their account:

1. **Their contributions to labs stay, anonymised.** Posts, comments, figure comments,
   figures and lab-visible maps remain, shown as by **"Former member"**. This matches the
   Privacy page: "What you posted to a lab stays with that lab, attributed to a deleted user."
2. **Their personal data goes:** profile, email, memberships, reactions, reading list,
   notifications, visits, private maps, sessions, and Claude grants.
3. **Labs:**
   - If they are the **last owner of a lab with other members**, deletion is **blocked** with:
     "Make someone else an owner of *Lab* first." This is the same rule `leave_team` already
     enforces.
   - If they are the **only member** of a lab, that lab is **deleted with it**. The
     confirmation dialog names these labs and how many papers each has.
4. **Their wish for content removal is still honoured by email.** Privacy keeps "unless you ask
   for it to be removed too".

## How

### Migration

- `comments.author_id` and `figure_comments.author_id` become **nullable, `ON DELETE SET NULL`**.
  Today they cascade.
- `maps.created_by` becomes nullable, `ON DELETE SET NULL`.
- Lab owners may remove (not edit) orphaned comments, figure comments, figures, figure files and
  maps; see below.

### One SQL function, run by the API

`delete_account(p_user uuid, p_confirm_email text)`, `SECURITY DEFINER`, **service role only**.
POST /account/delete calls it for the user id verified from the caller's token, so no user,
and no connector token, can call it directly or name another user, and the file cleanup after
it can't be skipped.

All steps run in one transaction, so a failure leaves nothing half-done:
1. Check the email matches.
2. Lock the user's labs (`FOR UPDATE`), so a join or a co-owner's simultaneous deletion can't
   overtake the checks.
3. Raise if they are the last owner of any lab with other members, naming the labs.
4. Delete labs where they are the only member, and those labs' removal tombstones.
5. Null their id in `removed_posts` elsewhere. `restore_post` copies `posted_by` back, so this
   keeps undo working.
6. Delete their private maps.
7. `delete from auth.users`. This cascades personal data and nulls the attributions.

Lab owners may **remove** (not edit) comments, figure comments, figures, figure files and maps
whose author is gone. Indexes on every `SET NULL` author column keep the deletion from scanning
whole tables.

### API

`POST /account/delete` (`require_token` + `get_user_id`, the existing pattern):
- runs `delete_account` with the service role;
- then removes the deleted solo labs' figure files;
- returns 204, or 409 with the user-facing message on a refusal.

### Web

- **Settings → "Delete account"** panel (danger zone), below Leave lab.
- **Dialog:**
  - what goes and what stays;
  - any blocking labs, with a link to Lab management;
  - any solo labs that will be deleted;
  - type your email to confirm.
- On success: sign out locally, and go to `/` with a "Your account has been deleted" notice.
- Comments with a null author read **"Former member"**; papers, figures and maps simply show no name. Lab owners get a **Remove** control on former members' comments.

### Privacy and Terms copy

Replace "To delete your account, email…" with "You can delete your account in Settings. Your
account details are removed immediately; backups expire within [N] days." Check the Supabase
plan's backup retention before writing N.

## Tests

Integration tests against local Supabase (`tests/local_supabase.py`, as in
`test_mcp_isolation_integration.py`):

- **Two-member lab:** member A has a post, a comment, a reaction, a private map and a lab map.
  A deletes their account:
  - the post, comment and lab map remain with null author;
  - the reaction and private map are gone;
  - A's auth user, profile and membership are gone;
  - B sees everything else unchanged.
- **Last owner with other members:** blocked, and nothing is deleted.
- **Sole member:** their lab and its posts are deleted; no other lab is touched.
- **Wrong confirmation email:** refused.
- **A user or connector token** calling `delete_account` directly: refused. Undo still works for a removed paper whose poster deleted their account. A lab owner can remove a former member's leftovers but not a current member's.
- After deletion, the user's old connector token gets `ATLAS_CONNECTOR_REVOKED`, and
  `GET /profile` with their web token returns 401.

Plus web typecheck/build, a run of the Settings flow with Playwright, and `/code-review high`.

## Decisions (made 2026-10-18)

All four: the recommended option.


1. Keep a deleted user's comments, anonymised as "Former member"? Or delete them (today's
   behaviour, which contradicts the Privacy page)?
2. Last owner of a lab with other members: block until they promote someone? Or auto-promote
   the longest-standing member?
3. Only member of a lab: delete the lab with the account? Or keep it ownerless?
4. Shared topic maps they made: keep as "Former member"? Or delete?
