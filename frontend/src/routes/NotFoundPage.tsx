import React from "react";
import { Link } from "react-router-dom";
import { AlertCircle } from "lucide-react";

export const NotFoundPage: React.FC = () => {
  return (
    <div className="py-20 text-center max-w-md mx-auto">
      <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-amber-950/40 border border-amber-800/80 flex items-center justify-center text-amber-400">
        <AlertCircle className="w-8 h-8" />
      </div>
      <h1 className="text-2xl font-bold text-gray-100">404 - Page Not Found</h1>
      <p className="text-xs text-gray-400 mt-2">
        The requested simulator view or dashboard route does not exist.
      </p>
      <Link
        to="/"
        className="mt-6 inline-block px-4 py-2 bg-primary/20 hover:bg-primary/30 text-primary border border-primary/40 rounded-lg text-xs font-semibold transition"
      >
        Return to Operations Command Center
      </Link>
    </div>
  );
};

export default NotFoundPage;
