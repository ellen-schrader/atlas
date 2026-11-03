import { FolderOpen, Lock, Radar, Users } from "lucide-react";

import { useDocumentTitle } from "@/hooks/useDocumentTitle";

/** What a project will do, one line each. */
const COMING = [
  { icon: FolderOpen, text: "Keep the papers for one piece of work together, without adding them to your reading list." },
  { icon: Radar, text: "See how close each library paper is to the project, and what has arrived nearby." },
  { icon: Users, text: "Share it with the whole lab, a few people, or keep it to yourself." },
];

/** Placeholder for Projects (docs/PROJECTS_PLAN.md) while it is built. Topic
 *  maps and the figure gallery were retired to make room; their old URLs
 *  redirect here. */
export default function Projects() {
  useDocumentTitle("Projects");
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-display font-bold tracking-tight">Projects</h1>
        <p className="mt-1.5 text-sm text-muted">Coming soon.</p>
      </div>

      <section
        aria-labelledby="projects-soon"
        className="flex flex-col gap-5 rounded-card border border-border bg-surface p-6 sm:p-8"
      >
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-surface-2 text-accent">
            <Lock size={18} aria-hidden />
          </span>
          <h2 id="projects-soon" className="text-lg font-semibold tracking-tight">
            Projects are on their way
          </h2>
        </div>
        <ul className="flex flex-col gap-3">
          {COMING.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-start gap-3 text-sm text-fg">
              <Icon size={16} aria-hidden className="mt-0.5 shrink-0 text-muted" />
              {text}
            </li>
          ))}
        </ul>
        <p className="border-t border-border pt-4 text-meta text-faint">
          Topic maps and the figure gallery have been retired to make room for this.
        </p>
      </section>
    </div>
  );
}
