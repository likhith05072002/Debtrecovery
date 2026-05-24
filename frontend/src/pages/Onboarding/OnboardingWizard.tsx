import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import client from "@/api/client";

interface OnboardingStatus {
  current_step: string;
  steps_completed: Record<string, any>;
  activation_score: number;
}

const STEPS = [
  { id: "phone", title: "Connect Phone", description: "Set up your outbound caller ID" },
  { id: "borrowers", title: "Upload Borrowers", description: "Import your borrower portfolio" },
  { id: "voice", title: "Configure Voice", description: "Test your AI agent's voice" },
  { id: "compliance", title: "Compliance Setup", description: "Configure FDCPA call windows and rules" },
  { id: "campaign", title: "First Campaign", description: "Launch a test campaign" },
  { id: "first_call", title: "Review Results", description: "See your first AI call in action" },
];

export default function OnboardingWizard() {
  const navigate = useNavigate();
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<any>(null);

  const { data: status, refetch } = useQuery<OnboardingStatus>({
    queryKey: ["onboarding-status"],
    queryFn: () => client.get("/onboarding/status").then((r) => r.data),
  });

  const completeMutation = useMutation({
    mutationFn: (data: { step: string; data?: any }) =>
      client.post("/onboarding/complete-step", data),
    onSuccess: () => refetch(),
  });

  const currentStepIndex = STEPS.findIndex((s) => s.id === status?.current_step);

  if (status?.current_step === "complete") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md">
          <div className="text-5xl mb-4">&#10003;</div>
          <h1 className="text-2xl font-bold text-gray-900">You're all set!</h1>
          <p className="text-gray-500 mt-2">
            Your AI collection agent is ready to make calls.
          </p>
          <button
            onClick={() => navigate("/")}
            className="mt-6 px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
          >
            Go to Dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Set Up Your AI Agent</h1>
          <p className="text-gray-500 mt-1">
            Complete these steps to start collecting — takes about 10 minutes.
          </p>
        </div>

        {/* Progress Bar */}
        <div className="flex items-center justify-between mb-10 px-4">
          {STEPS.map((step, i) => {
            const isCompleted = status?.steps_completed?.[step.id];
            const isCurrent = step.id === status?.current_step;
            return (
              <div key={step.id} className="flex items-center">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                    isCompleted
                      ? "bg-green-500 text-white"
                      : isCurrent
                      ? "bg-blue-600 text-white"
                      : "bg-gray-200 text-gray-500"
                  }`}
                >
                  {isCompleted ? "\u2713" : i + 1}
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={`w-8 h-0.5 mx-1 ${
                      isCompleted ? "bg-green-500" : "bg-gray-200"
                    }`}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Current Step Content */}
        <div className="bg-white rounded-xl shadow-lg p-8">
          {status?.current_step === "phone" && (
            <StepPhone onComplete={() => completeMutation.mutate({ step: "phone" })} />
          )}
          {status?.current_step === "borrowers" && (
            <StepBorrowers
              csvFile={csvFile}
              setCsvFile={setCsvFile}
              uploadResult={uploadResult}
              setUploadResult={setUploadResult}
              onComplete={() => completeMutation.mutate({ step: "borrowers" })}
            />
          )}
          {status?.current_step === "voice" && (
            <StepVoice onComplete={() => completeMutation.mutate({ step: "voice" })} />
          )}
          {status?.current_step === "compliance" && (
            <StepCompliance onComplete={() => completeMutation.mutate({ step: "compliance" })} />
          )}
          {status?.current_step === "campaign" && (
            <StepCampaign onComplete={() => completeMutation.mutate({ step: "campaign" })} />
          )}
          {status?.current_step === "first_call" && (
            <StepFirstCall onComplete={() => completeMutation.mutate({ step: "first_call" })} />
          )}
        </div>

        {/* Skip option */}
        <p className="text-center mt-4 text-sm text-gray-400">
          <button onClick={() => navigate("/")} className="hover:underline">
            Skip setup and go to dashboard
          </button>
        </p>
      </div>
    </div>
  );
}

// ── Step Components ──────────────────────────────────────────────────────────

function StepPhone({ onComplete }: { onComplete: () => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-2">Connect Your Phone Number</h2>
      <p className="text-gray-500 mb-6">
        We'll use this number as your outbound caller ID. You can use a Twilio number or bring your own.
      </p>
      <div className="space-y-4">
        <div className="p-4 border rounded-lg bg-blue-50 border-blue-200">
          <p className="text-sm text-blue-800 font-medium">Default number configured:</p>
          <p className="text-lg font-mono mt-1">+1 (213) 838-7179</p>
        </div>
        <button
          onClick={onComplete}
          className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
        >
          Use This Number & Continue
        </button>
      </div>
    </div>
  );
}

function StepBorrowers({
  csvFile, setCsvFile, uploadResult, setUploadResult, onComplete,
}: {
  csvFile: File | null;
  setCsvFile: (f: File | null) => void;
  uploadResult: any;
  setUploadResult: (r: any) => void;
  onComplete: () => void;
}) {
  async function handleUpload() {
    if (!csvFile) return;
    const formData = new FormData();
    formData.append("file", csvFile);
    const { data } = await client.post("/onboarding/upload-borrowers", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    setUploadResult(data);
  }

  return (
    <div>
      <h2 className="text-xl font-semibold mb-2">Upload Your Borrowers</h2>
      <p className="text-gray-500 mb-6">
        Upload a CSV with your borrower portfolio. Required columns: external_id, phone, principal_amount, current_balance.
      </p>
      <div className="space-y-4">
        <input
          type="file"
          accept=".csv"
          onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
          className="block w-full text-sm border rounded-lg p-2"
        />
        {csvFile && !uploadResult && (
          <button
            onClick={handleUpload}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg"
          >
            Preview Upload
          </button>
        )}
        {uploadResult && (
          <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-green-800 font-medium">
              {uploadResult.rows_found} borrowers ready to import
            </p>
            <p className="text-sm text-green-600 mt-1">
              Columns found: {uploadResult.columns.join(", ")}
            </p>
          </div>
        )}
        <button
          onClick={onComplete}
          disabled={!uploadResult}
          className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          Import & Continue
        </button>
      </div>
    </div>
  );
}

function StepVoice({ onComplete }: { onComplete: () => void }) {
  const [testing, setTesting] = useState(false);

  async function testVoice() {
    setTesting(true);
    await client.post("/onboarding/voice-test");
    setTimeout(() => setTesting(false), 3000);
  }

  return (
    <div>
      <h2 className="text-xl font-semibold mb-2">Test Your AI Voice</h2>
      <p className="text-gray-500 mb-6">
        Hear how your AI agent sounds. We'll call your phone with a sample introduction.
      </p>
      <div className="space-y-4">
        <button
          onClick={testVoice}
          disabled={testing}
          className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-50"
        >
          {testing ? "Calling you..." : "Call My Phone"}
        </button>
        <button
          onClick={onComplete}
          className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
        >
          Sounds Good — Continue
        </button>
      </div>
    </div>
  );
}

function StepCompliance({ onComplete }: { onComplete: () => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-2">Compliance Configuration</h2>
      <p className="text-gray-500 mb-6">
        Your AI agent comes pre-configured for FDCPA compliance. Review and confirm these settings.
      </p>
      <div className="space-y-3 mb-6">
        <div className="flex justify-between p-3 bg-gray-50 rounded">
          <span className="text-sm">Call Window</span>
          <span className="text-sm font-medium">8:00 AM - 9:00 PM (borrower local time)</span>
        </div>
        <div className="flex justify-between p-3 bg-gray-50 rounded">
          <span className="text-sm">Max Calls per Day</span>
          <span className="text-sm font-medium">1</span>
        </div>
        <div className="flex justify-between p-3 bg-gray-50 rounded">
          <span className="text-sm">Max Calls per Week</span>
          <span className="text-sm font-medium">3</span>
        </div>
        <div className="flex justify-between p-3 bg-gray-50 rounded">
          <span className="text-sm">Auto Opt-Out Detection</span>
          <span className="text-sm font-medium text-green-600">Enabled</span>
        </div>
        <div className="flex justify-between p-3 bg-gray-50 rounded">
          <span className="text-sm">Mini-Miranda Enforcement</span>
          <span className="text-sm font-medium text-green-600">Enabled</span>
        </div>
      </div>
      <button
        onClick={onComplete}
        className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
      >
        Confirm Settings & Continue
      </button>
    </div>
  );
}

function StepCampaign({ onComplete }: { onComplete: () => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-2">Launch Test Campaign</h2>
      <p className="text-gray-500 mb-6">
        We'll create a small test campaign with 5 borrowers to demonstrate the AI agent.
      </p>
      <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg mb-6">
        <p className="text-sm text-yellow-800">
          This will place real calls to real borrowers. Only proceed if your borrower data is ready.
        </p>
      </div>
      <button
        onClick={onComplete}
        className="w-full py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
      >
        Launch Test Campaign
      </button>
    </div>
  );
}

function StepFirstCall({ onComplete }: { onComplete: () => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold mb-2">Review Your Results</h2>
      <p className="text-gray-500 mb-6">
        Your test campaign is running! Once calls complete, you'll see results on the dashboard.
      </p>
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg mb-6">
        <p className="text-sm text-blue-800">
          Calls typically take 30-60 seconds each. Results appear in real-time on the dashboard.
        </p>
      </div>
      <button
        onClick={onComplete}
        className="w-full py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700"
      >
        Complete Setup & View Dashboard
      </button>
    </div>
  );
}
