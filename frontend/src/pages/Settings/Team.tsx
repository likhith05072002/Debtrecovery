import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface TeamMember {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export default function Team() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("agent");

  const { data: members = [], isLoading } = useQuery<TeamMember[]>({
    queryKey: ["users"],
    queryFn: () => client.get("/users").then((r) => r.data),
  });

  const inviteMutation = useMutation({
    mutationFn: (data: { email: string; role: string }) =>
      client.post("/users/invite", data),
    onSuccess: () => {
      setShowInvite(false);
      setInviteEmail("");
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: string; is_active?: boolean }) =>
      client.patch(`/users/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const isAdmin = user?.role === "owner" || user?.role === "admin";

  if (isLoading) return <div className="p-6">Loading team...</div>;

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Team Members</h1>
        {isAdmin && (
          <button
            onClick={() => setShowInvite(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            Invite Member
          </button>
        )}
      </div>

      {showInvite && (
        <div className="mb-6 p-4 bg-gray-50 rounded-lg border">
          <h3 className="font-medium mb-3">Invite New Member</h3>
          <div className="flex gap-3">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="email@company.com"
              className="flex-1 px-3 py-2 border rounded-lg"
            />
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              className="px-3 py-2 border rounded-lg"
            >
              <option value="agent">Agent</option>
              <option value="manager">Manager</option>
              <option value="admin">Admin</option>
              <option value="readonly">Read Only</option>
            </select>
            <button
              onClick={() => inviteMutation.mutate({ email: inviteEmail, role: inviteRole })}
              disabled={!inviteEmail || inviteMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50"
            >
              Send Invite
            </button>
            <button
              onClick={() => setShowInvite(false)}
              className="px-4 py-2 text-gray-600 hover:text-gray-800"
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
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Email</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Role</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Last Login</th>
              {isAdmin && <th className="px-4 py-3 text-right text-sm font-medium text-gray-600">Actions</th>}
            </tr>
          </thead>
          <tbody className="divide-y">
            {members.map((m) => (
              <tr key={m.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm">
                  {m.first_name} {m.last_name}
                  {m.id === user?.id && (
                    <span className="ml-2 text-xs text-gray-400">(you)</span>
                  )}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{m.email}</td>
                <td className="px-4 py-3">
                  <span className="inline-block px-2 py-0.5 text-xs font-medium rounded-full bg-blue-100 text-blue-800 capitalize">
                    {m.role}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${
                      m.is_active
                        ? "bg-green-100 text-green-800"
                        : "bg-red-100 text-red-800"
                    }`}
                  >
                    {m.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">
                  {m.last_login_at
                    ? new Date(m.last_login_at).toLocaleDateString()
                    : "Never"}
                </td>
                {isAdmin && (
                  <td className="px-4 py-3 text-right">
                    {m.id !== user?.id && m.role !== "owner" && (
                      <button
                        onClick={() =>
                          updateMutation.mutate({
                            id: m.id,
                            is_active: !m.is_active,
                          })
                        }
                        className="text-xs text-red-600 hover:underline"
                      >
                        {m.is_active ? "Deactivate" : "Activate"}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
