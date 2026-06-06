import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center text-center">
      <Card padding="lg" className="w-full">
        <div className="flex flex-col items-center gap-3 py-8">
          <div
            aria-hidden
            className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-2xl text-slate-500 dark:bg-slate-800 dark:text-slate-300"
          >
            ⌕
          </div>
          <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            Page not found
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            The page you were looking for doesn't exist or has moved.
          </p>
          <Link to="/">
            <Button variant="primary">Back to dashboard</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}
