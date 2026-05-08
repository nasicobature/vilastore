import { useState } from 'react';
import { useApp } from '@/lib/context';
import { SECONDARY_ROLES, TERTIARY_ROLES, UserRole } from '@/lib/store';
import { GraduationCap, ArrowLeft, LogIn } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function LoginPage() {
  const { institutionType, setInstitutionType, login } = useApp();
  const [selectedRole, setSelectedRole] = useState<UserRole | ''>('');
  const [name, setName] = useState('');

  const roles = institutionType === 'secondary' ? SECONDARY_ROLES : TERTIARY_ROLES;
  const label = institutionType === 'secondary' ? 'Secondary School' : 'Tertiary Institution';

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedRole && name.trim()) {
      login(selectedRole as UserRole, name.trim());
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <button
          onClick={() => setInstitutionType(null)}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors"
        >
          <ArrowLeft size={16} /> Back to selection
        </button>

        <div className="bg-card border border-border rounded-2xl p-8">
          <div className="text-center mb-6">
            <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center mx-auto mb-3">
              <GraduationCap className="text-primary-foreground" size={24} />
            </div>
            <h2 className="font-display text-2xl font-bold">Sign In</h2>
            <p className="text-sm text-muted-foreground mt-1">{label} Portal</p>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">Full Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Enter your name"
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1.5">Select Role</label>
              <select
                value={selectedRole}
                onChange={e => setSelectedRole(e.target.value as UserRole)}
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                required
              >
                <option value="">Choose your role...</option>
                {roles.map(r => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1.5">Password</label>
              <input
                type="password"
                placeholder="Enter password"
                defaultValue="demo123"
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">Demo mode — any password works</p>
            </div>

            <Button type="submit" className="w-full" disabled={!selectedRole || !name.trim()}>
              <LogIn size={16} /> Sign In
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
