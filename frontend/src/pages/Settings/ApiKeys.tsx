import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "@/api/client";

interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[] | null;
  is_active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export default function ApiKeys() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const { data: keys = [], isLoading } = useQuery<ApiKeyItem[]>({
    queryKey: ["api-keys"],
    queryFn: () => client.get("/org/api-keys").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      client.post("/org/api-keys", { name, scopes: ["*"] }),
    onSuccess: (res) => {
      setCreatedKey(res.data.key);
      setShowCreate(false);
      setNewKeyName("");
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => client.delete(`/org/api-keys/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  if (isLoading) return <div className="p-6">Loading API keys...</div>;

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="text-gray-500 text-sm mt-1">
            Use API keys to authenticate programmatic access to the DebtCollector API.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
        >
          Create Key
        </button>
      </div>

      {createdKey && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
          <p className="text-sm font-medium text-green-800 mb-2">
            API key created! Copy it now — you won't be able to see it again.
          </p>
          <code className="block p-2 bg-white rounded border text-sm font-mono break-all">
            {createdKey}
          </code>
          <button
            onClick={() => {
              navigator.clipboard.writeText(createdKey);
            }}
            className="mt-2 text-sm text-green-700 hover:underline"
          >
            Copy to clipboard
          </button>
          <button
            onClick={() => setCreatedKey(null)}
            className="mt-2 ml-4 text-sm text-gray-500 hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {showCreate && (
        <div className="mb-6 p-4 bg-gray-50 rounded-lg border">
          <h3 className="font-medium mb-3">Create New API Key</h3>
          <div className="flex gap-3">
            <input
              type="text"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder="Key name (e.g., Production Backend)"
              className="flex-1 px-3 py-2 border rounded-lg"
            />
            <button
              onClick={() => createMutation.mutate(newKeyName)}
              disabled={!newKeyName || createMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50"
            >
              Create
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 text-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Name</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Key</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Last Used</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Created</th>
              <th className="px-4 py-3 text-right text-sm font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {keys.map((k) => (
              <tr key={k.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-medium">{k.name}</td>
                <td className="px-4 py-3 text-sm font-mono text-gray-500">
                  {k.key_prefix}...
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${
                      k.is_active
                        ? "bg-green-100 text-green-800"
                        : "bg-red-100 text-red-800"
                    }`}
                  >
                    {k.is_active ? "Active" : "Revoked"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">
                  {k.last_used_at
                    ? new Date(k.last_used_at).toLocaleDateString()
                    : "Never"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">
                  {new Date(k.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  {k.is_active && (
                    <button
                      onClick={() => revokeMutation.mutate(k.id)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {keys.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  No API keys yet. Create one to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
