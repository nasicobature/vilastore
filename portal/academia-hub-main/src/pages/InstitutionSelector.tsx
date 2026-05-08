import { useApp } from '@/lib/context';
import { School, Building2, GraduationCap } from 'lucide-react';

export default function InstitutionSelector() {
  const { setInstitutionType } = useApp();

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
      <div className="text-center mb-12">
        <div className="w-16 h-16 rounded-2xl bg-primary flex items-center justify-center mx-auto mb-4">
          <GraduationCap className="text-primary-foreground" size={32} />
        </div>
        <h1 className="font-display text-4xl font-bold mb-2">EduPortal</h1>
        <p className="text-muted-foreground text-lg">School Management System</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-2xl w-full">
        <button
          onClick={() => setInstitutionType('secondary')}
          className="group bg-card border-2 border-border rounded-2xl p-8 text-left hover:border-primary hover:shadow-lg transition-all duration-300"
        >
          <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
            <School size={28} className="text-primary group-hover:text-primary-foreground" />
          </div>
          <h2 className="font-display text-xl font-bold mb-2">Secondary School</h2>
          <p className="text-sm text-muted-foreground">
            Manage JSS1–SS3 classes, teachers, exams, results, and school fees with role-based access.
          </p>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {['Admin', 'Registry', 'Teacher', 'Student'].map(r => (
              <span key={r} className="text-xs bg-muted rounded-full px-2.5 py-1">{r}</span>
            ))}
          </div>
        </button>

        <button
          onClick={() => setInstitutionType('tertiary')}
          className="group bg-card border-2 border-border rounded-2xl p-8 text-left hover:border-secondary hover:shadow-lg transition-all duration-300"
        >
          <div className="w-14 h-14 rounded-xl bg-secondary/10 flex items-center justify-center mb-4 group-hover:bg-secondary group-hover:text-secondary-foreground transition-colors">
            <Building2 size={28} className="text-secondary group-hover:text-secondary-foreground" />
          </div>
          <h2 className="font-display text-xl font-bold mb-2">Tertiary Institution</h2>
          <p className="text-sm text-muted-foreground">
            University/polytechnic management with faculties, departments, CBT, and hierarchical approval.
          </p>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {['VC', 'ICT Admin', 'Lecturer', 'Student'].map(r => (
              <span key={r} className="text-xs bg-muted rounded-full px-2.5 py-1">{r}</span>
            ))}
          </div>
        </button>
      </div>
    </div>
  );
}
