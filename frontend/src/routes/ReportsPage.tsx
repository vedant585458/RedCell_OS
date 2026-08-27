import React from "react";
import { FileText, Download, CheckCircle, Award } from "lucide-react";

export const ReportsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <FileText className="w-5 h-5 text-primary" />
            Security Reports & Deliverables
          </h1>
          <p className="text-xs text-gray-400 mt-1">
            Automated executive summaries, technical vulnerability findings, and CVSS matrices.
          </p>
        </div>

        <button className="px-3.5 py-2 bg-primary/20 hover:bg-primary/30 text-primary border border-primary/40 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition">
          <Download className="w-4 h-4" />
          Export Sealed Audit Bundle (.zip)
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 bg-surface rounded-xl border border-surfaceBorder p-5">
          <h2 className="text-sm font-semibold text-gray-100 pb-3 border-b border-surfaceBorder flex items-center gap-2">
            <Award className="w-4 h-4 text-amber-400" />
            Generated Assessment Deliverables
          </h2>

          <div className="mt-4 p-4 bg-background/80 rounded-lg border border-surfaceBorder flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold text-gray-200">
                report_eng-mvp-001.md
              </div>
              <div className="text-xs text-gray-400 mt-0.5">
                Target: http://127.0.0.1:8088 | Findings: 1 High (CVSS 7.5) | Format: Markdown
              </div>
            </div>
            <button className="px-3 py-1.5 bg-surface hover:bg-surfaceBorder text-gray-200 text-xs rounded border border-surfaceBorder flex items-center gap-1 transition">
              <Download className="w-3.5 h-3.5" />
              Download
            </button>
          </div>
        </div>

        <div className="bg-surface rounded-xl border border-surfaceBorder p-5">
          <h2 className="text-sm font-semibold text-gray-100 flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            Audit & Compliance Scoring
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Automated mapping against MITRE ATT&CK and OWASP Top 10.
          </p>

          <div className="mt-4 space-y-2 text-xs">
            <div className="flex justify-between p-2 rounded bg-background">
              <span className="text-gray-400">OWASP A01:2021:</span>
              <span className="text-emerald-400 font-semibold">Tested (1 Finding)</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-background">
              <span className="text-gray-400">MITRE ATT&CK:</span>
              <span className="text-primary font-semibold">TA0043, TA0007</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-background">
              <span className="text-gray-400">Audit Provenance:</span>
              <span className="text-purple-400 font-mono">100% Verified</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ReportsPage;
