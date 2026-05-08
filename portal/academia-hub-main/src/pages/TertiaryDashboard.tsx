import React, { useState, useEffect, useCallback } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import StatCard from '@/components/StatCard';
import DataTable from '@/components/DataTable';
import { Button } from '@/components/ui/button';
import {
  Users, BookOpen, Building2, GraduationCap, CreditCard, ClipboardCheck, Monitor,
  Plus, Download, Check, X, Eye, Edit, Settings, Upload, Play, Clock
} from 'lucide-react';
import {
  dashboardStats, mockFaculties, mockDepartments, mockCourses, mockLecturers,
  mockTertiaryStudents, mockCBTExams, mockCBTQuestions, mockPayments, mockFees
} from '@/lib/mock-data';
import { useApp } from '@/lib/context';

function VCDashboard({ page }: { page: string }) {
  const stats = dashboardStats.tertiary;
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">VC / Provost Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Total Students" value={stats.totalStudents.toLocaleString()} icon={<Users size={20} />} trend="+5.2%" trendUp color="primary" />
        <StatCard title="Total Lecturers" value={stats.totalLecturers} icon={<GraduationCap size={20} />} color="secondary" />
        <StatCard title="Faculties" value={stats.totalFaculties} icon={<Building2 size={20} />} color="accent" />
        <StatCard title="Graduation Rate" value={`${stats.graduationRate}%`} icon={<GraduationCap size={20} />} trend="+2.1%" trendUp color="info" />
      </div>
      <DataTable title="Faculties Overview" columns={[
        { key: 'name', label: 'Faculty' }, { key: 'dean', label: 'Dean' }, { key: 'departments', label: 'Departments' }
      ]} data={mockFaculties} />
    </div>
  );
  if (page === 'approve-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Approve Final Results</h2>
      {mockDepartments.map((d, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div><p className="font-medium">{d.name} - 2024/2025 Results</p><p className="text-sm text-muted-foreground">{d.faculty}</p></div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm"><Eye size={14} /> Review</Button>
            <Button size="sm" className="bg-secondary hover:bg-secondary/90"><Check size={14} /> Approve</Button>
          </div>
        </div>
      ))}
    </div>
  );
  if (page === 'analytics') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Institution Analytics</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[{ t: 'Enrollment Trend', v: '8,500' }, { t: 'Revenue', v: '₦425M' }, { t: 'Staff Count', v: '520' }, { t: 'Research Output', v: '142 papers' }].map(a => (
          <div key={a.t} className="bg-card border border-border rounded-xl p-6 text-center">
            <p className="text-sm text-muted-foreground">{a.t}</p>
            <p className="text-3xl font-display font-bold text-primary mt-1">{a.v}</p>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'faculties') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Manage Faculties</h2>
        <Button><Plus size={16} /> Add Faculty</Button>
      </div>
      <DataTable columns={[
        { key: 'name', label: 'Faculty' }, { key: 'dean', label: 'Dean' }, { key: 'departments', label: 'Depts' },
        { key: 'actions', label: '', render: () => <div className="flex gap-1"><button className="p-1 hover:bg-muted rounded"><Edit size={14} /></button></div> }
      ]} data={mockFaculties} />
    </div>
  );
  return <p>Page not found</p>;
}

function ICTAdminDashboard({ page }: { page: string }) {
  const stats = dashboardStats.tertiary;
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">ICT Admin Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="CBT Exams Created" value={stats.cbtExamsCreated} icon={<Monitor size={20} />} color="primary" />
        <StatCard title="Active Exams" value="3" icon={<Play size={20} />} color="secondary" />
        <StatCard title="Total Users" value="9,340" icon={<Users size={20} />} color="accent" />
        <StatCard title="Question Bank" value="4,520" icon={<BookOpen size={20} />} color="info" />
      </div>
      <DataTable title="Recent CBT Exams" columns={[
        { key: 'title', label: 'Exam' }, { key: 'course', label: 'Course' }, { key: 'questions', label: 'Questions' },
        { key: 'duration', label: 'Duration', render: (v: number) => `${v} mins` },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Active' ? 'bg-secondary/10 text-secondary' : v === 'Scheduled' ? 'bg-accent/10 text-accent' : 'bg-muted text-muted-foreground'}`}>{v}</span> }
      ]} data={mockCBTExams} />
    </div>
  );
  if (page === 'cbt-exams') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">CBT Exams</h2>
        <Button><Plus size={16} /> Create Exam</Button>
      </div>
      <div className="bg-card border border-border rounded-xl p-6 max-w-lg space-y-4">
        <h3 className="font-display font-semibold">Create New CBT Exam</h3>
        {[{ l: 'Exam Title', p: 'e.g. CSC101 Mid-Semester' }, { l: 'Course Code', p: 'e.g. CSC101' }].map(f => (
          <div key={f.l}><label className="text-sm font-medium">{f.l}</label><input className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1" placeholder={f.p} /></div>
        ))}
        <div className="grid grid-cols-2 gap-3">
          <div><label className="text-sm font-medium">Duration (mins)</label><input type="number" className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1" defaultValue={30} /></div>
          <div><label className="text-sm font-medium">No. of Questions</label><input type="number" className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1" defaultValue={30} /></div>
        </div>
        <div><label className="text-sm font-medium">Assign to Department</label>
          <select className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1">{mockDepartments.map(d => <option key={d.id}>{d.name}</option>)}</select>
        </div>
        <div className="flex items-center gap-2"><input type="checkbox" id="showScore" /><label htmlFor="showScore" className="text-sm">Show score immediately after submission</label></div>
        <Button className="w-full">Create Exam</Button>
      </div>
    </div>
  );
  if (page === 'questions') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Question Bank</h2>
        <Button><Plus size={16} /> Add Question</Button>
      </div>
      {mockCBTQuestions.map(q => (
        <div key={q.id} className="bg-card border border-border rounded-xl p-4">
          <p className="font-medium text-sm mb-2">Q{q.id}. {q.question}</p>
          <div className="grid grid-cols-2 gap-2">
            {q.options.map((o, i) => (
              <div key={i} className={`text-xs px-3 py-2 rounded-lg border ${i === q.answer ? 'border-secondary bg-secondary/10 text-secondary font-medium' : 'border-border'}`}>
                {String.fromCharCode(65 + i)}) {o}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
  if (page === 'users') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Manage Users</h2>
        <Button><Plus size={16} /> Add User</Button>
      </div>
      <DataTable columns={[
        { key: 'name', label: 'Name' }, { key: 'matric', label: 'Matric No.' }, { key: 'department', label: 'Department' }, { key: 'level', label: 'Level' }
      ]} data={mockTertiaryStudents} />
    </div>
  );
  if (page === 'grading') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Grading System Configuration</h2>
      <div className="bg-card border border-border rounded-xl p-6 max-w-md">
        {[{ grade: 'A', range: '70-100', gp: '5.0' }, { grade: 'B', range: '60-69', gp: '4.0' }, { grade: 'C', range: '50-59', gp: '3.0' }, { grade: 'D', range: '45-49', gp: '2.0' }, { grade: 'E', range: '40-44', gp: '1.0' }, { grade: 'F', range: '0-39', gp: '0.0' }].map(g => (
          <div key={g.grade} className="flex items-center justify-between py-2 border-b border-border last:border-0">
            <span className="font-bold text-primary">{g.grade}</span>
            <span className="text-sm">{g.range}%</span>
            <span className="text-sm text-muted-foreground">GP: {g.gp}</span>
          </div>
        ))}
        <Button className="mt-4 w-full">Save Configuration</Button>
      </div>
    </div>
  );
  return <p>Page not found</p>;
}

function TertiaryAccountantDashboard({ page }: { page: string }) {
  const stats = dashboardStats.tertiary;
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Accountant Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Fees Collected" value={`₦${(stats.feesCollected / 1e6).toFixed(0)}M`} icon={<CreditCard size={20} />} trend="+12%" trendUp color="secondary" />
        <StatCard title="Fees Pending" value={`₦${(stats.feesPending / 1e6).toFixed(0)}M`} icon={<CreditCard size={20} />} color="accent" />
        <StatCard title="Payments Today" value="45" icon={<CreditCard size={20} />} color="primary" />
        <StatCard title="Receipts" value="6,820" icon={<ClipboardCheck size={20} />} color="info" />
      </div>
      <DataTable title="Recent Payments" columns={[
        { key: 'studentName', label: 'Student' }, { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` },
        { key: 'date', label: 'Date' },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Paid' ? 'bg-secondary/10 text-secondary' : 'bg-accent/10 text-accent'}`}>{v}</span> }
      ]} data={mockPayments} />
    </div>
  );
  if (page === 'fees') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">School Fees</h2><Button><Plus size={16} /> Create Fee</Button></div>
      <DataTable columns={[
        { key: 'name', label: 'Fee Type' }, { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` }, { key: 'term', label: 'Semester' }, { key: 'session', label: 'Session' }
      ]} data={mockFees} />
    </div>
  );
  if (page === 'payments') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Accept Payments</h2><Button><Plus size={16} /> Record Payment</Button></div>
      <DataTable columns={[
        { key: 'receipt', label: 'Receipt #' }, { key: 'studentName', label: 'Student' },
        { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` }, { key: 'date', label: 'Date' },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Paid' ? 'bg-secondary/10 text-secondary' : 'bg-accent/10 text-accent'}`}>{v}</span> }
      ]} data={mockPayments} />
    </div>
  );
  if (page === 'receipts') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Receipts</h2>
      <DataTable columns={[
        { key: 'receipt', label: 'Receipt #' }, { key: 'studentName', label: 'Student' },
        { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` }, { key: 'date', label: 'Date' },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Download size={14} /> Download</Button> }
      ]} data={mockPayments} />
    </div>
  );
  if (page === 'reports') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Financial Reports</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {['Revenue Summary', 'Outstanding Fees', 'Department-wise Collection', 'Semester Report'].map(r => (
          <div key={r} className="bg-card border border-border rounded-xl p-6 text-center">
            <p className="font-medium mb-2">{r}</p>
            <p className="text-3xl font-display font-bold text-primary">₦{(Math.random() * 200 + 50).toFixed(0)}M</p>
            <Button variant="outline" size="sm" className="mt-3"><Download size={14} /> Export</Button>
          </div>
        ))}
      </div>
    </div>
  );
  return <p>Page not found</p>;
}

function FacultyAdminDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Faculty Admin Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard title="Departments" value="5" icon={<Building2 size={20} />} color="primary" />
        <StatCard title="Lecturers" value="42" icon={<GraduationCap size={20} />} color="secondary" />
        <StatCard title="Students" value="1,850" icon={<Users size={20} />} color="accent" />
      </div>
      <DataTable title="Departments" columns={[
        { key: 'name', label: 'Department' }, { key: 'hod', label: 'HOD' }, { key: 'students', label: 'Students' }
      ]} data={mockDepartments} />
    </div>
  );
  if (page === 'departments') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Manage Departments</h2><Button><Plus size={16} /> Add Department</Button></div>
      <DataTable columns={[
        { key: 'name', label: 'Department' }, { key: 'hod', label: 'HOD' }, { key: 'students', label: 'Students' },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Edit size={14} /> Edit</Button> }
      ]} data={mockDepartments} />
    </div>
  );
  if (page === 'performance') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Faculty Performance</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {mockDepartments.map(d => (
          <div key={d.id} className="bg-card border border-border rounded-xl p-5">
            <p className="font-display font-semibold">{d.name}</p>
            <p className="text-sm text-muted-foreground">{d.hod}</p>
            <div className="mt-3 flex justify-between text-sm">
              <span>Pass Rate: <strong className="text-secondary">{(Math.random() * 20 + 75).toFixed(1)}%</strong></span>
              <span>Students: <strong>{d.students}</strong></span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'approve-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Approve Department Results</h2>
      {mockDepartments.map((d, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div><p className="font-medium">{d.name}</p><p className="text-sm text-muted-foreground">Submitted by {d.hod}</p></div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm"><Eye size={14} /> Review</Button>
            <Button size="sm" className="bg-secondary hover:bg-secondary/90"><Check size={14} /> Approve</Button>
          </div>
        </div>
      ))}
    </div>
  );
  return <p>Page not found</p>;
}

function DeptAdminDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Department Admin Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Students" value="320" icon={<Users size={20} />} color="primary" />
        <StatCard title="Courses" value="24" icon={<BookOpen size={20} />} color="secondary" />
        <StatCard title="Lecturers" value="12" icon={<GraduationCap size={20} />} color="accent" />
        <StatCard title="Pending Results" value="3" icon={<ClipboardCheck size={20} />} color="info" />
      </div>
    </div>
  );
  if (page === 'students') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Students</h2><Button><Plus size={16} /> Register Student</Button></div>
      <DataTable columns={[
        { key: 'matric', label: 'Matric No.' }, { key: 'name', label: 'Name' }, { key: 'level', label: 'Level' },
        { key: 'gpa', label: 'GPA', render: (v: number) => <span className="font-semibold text-primary">{v.toFixed(2)}</span> }
      ]} data={mockTertiaryStudents} />
    </div>
  );
  if (page === 'courses') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Courses</h2><Button><Plus size={16} /> Add Course</Button></div>
      <DataTable columns={[
        { key: 'code', label: 'Code' }, { key: 'title', label: 'Title' }, { key: 'unit', label: 'Units' }, { key: 'semester', label: 'Semester' }
      ]} data={mockCourses} />
    </div>
  );
  if (page === 'lecturers') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Lecturers</h2><Button><Plus size={16} /> Assign Lecturer</Button></div>
      <DataTable columns={[
        { key: 'name', label: 'Name' }, { key: 'department', label: 'Department' },
        { key: 'courses', label: 'Courses', render: (v: string[]) => v.join(', ') }, { key: 'email', label: 'Email' }
      ]} data={mockLecturers} />
    </div>
  );
  if (page === 'submit-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Submit Results to Faculty</h2>
      {mockCourses.slice(0, 3).map((c, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div><p className="font-medium">{c.code} - {c.title}</p><p className="text-sm text-muted-foreground">Verified by examiner</p></div>
          <Button size="sm"><Upload size={14} /> Submit</Button>
        </div>
      ))}
    </div>
  );
  return <p>Page not found</p>;
}

function LecturerDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Lecturer Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="My Courses" value="2" icon={<BookOpen size={20} />} color="primary" />
        <StatCard title="My Students" value="185" icon={<Users size={20} />} color="secondary" />
        <StatCard title="Pending Submissions" value="1" icon={<Upload size={20} />} color="accent" />
        <StatCard title="Materials Uploaded" value="12" icon={<BookOpen size={20} />} color="info" />
      </div>
    </div>
  );
  if (page === 'my-courses') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Courses</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {mockCourses.slice(0, 2).map(c => (
          <div key={c.code} className="bg-card border border-border rounded-xl p-6">
            <p className="font-display text-lg font-bold text-primary">{c.code}</p>
            <p className="font-medium">{c.title}</p>
            <p className="text-sm text-muted-foreground">{c.unit} units • {c.semester} Semester</p>
          </div>
        ))}
      </div>
    </div>
  );
  if (page === 'my-students') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Students</h2>
      <DataTable columns={[
        { key: 'matric', label: 'Matric No.' }, { key: 'name', label: 'Name' }, { key: 'level', label: 'Level' }
      ]} data={mockTertiaryStudents} />
    </div>
  );
  if (page === 'enter-scores') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Enter Scores</h2>
      <div className="flex gap-3 mb-4">
        <select className="px-3 py-2 rounded-lg border border-input bg-background text-sm"><option>CSC101</option><option>CSC201</option></select>
        <select className="px-3 py-2 rounded-lg border border-input bg-background text-sm"><option>Test</option><option>Assignment</option><option>Exam</option></select>
      </div>
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <table className="w-full"><thead><tr className="bg-muted/50">
          <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">Student</th>
          <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">Matric</th>
          <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">Score</th>
        </tr></thead><tbody className="divide-y divide-border">
          {mockTertiaryStudents.map(s => (
            <tr key={s.id}><td className="px-4 py-2 text-sm">{s.name}</td><td className="px-4 py-2 text-sm">{s.matric}</td><td className="px-4 py-2"><input type="number" className="w-20 px-2 py-1 rounded border border-input bg-background text-sm" /></td></tr>
          ))}
        </tbody></table>
      </div>
      <Button>Save Scores</Button>
    </div>
  );
  if (page === 'materials') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Course Materials</h2><Button><Upload size={16} /> Upload Material</Button></div>
      {['CSC101 Lecture Notes - Week 1.pdf', 'CSC101 Assignment 1.pdf', 'CSC201 Data Structures Slides.pptx'].map((m, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3"><BookOpen size={20} className="text-primary" /><p className="text-sm font-medium">{m}</p></div>
          <Button variant="outline" size="sm"><Download size={14} /> Download</Button>
        </div>
      ))}
    </div>
  );
  if (page === 'submit-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Submit Results</h2>
      {['CSC101 - Introduction to CS', 'CSC201 - Data Structures'].map((c, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div><p className="font-medium">{c}</p><p className="text-sm text-muted-foreground">{i === 0 ? 'All scores entered' : '2 scores missing'}</p></div>
          <Button size="sm" disabled={i === 1}>Submit for Review</Button>
        </div>
      ))}
    </div>
  );
  return <p>Page not found</p>;
}

function TertiaryExaminerDashboard({ page }: { page: string }) {
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Examiner Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard title="Pending Reviews" value="4" icon={<ClipboardCheck size={20} />} color="accent" />
        <StatCard title="Verified" value="18" icon={<Check size={20} />} color="secondary" />
        <StatCard title="Flagged" value="2" icon={<X size={20} />} color="primary" />
      </div>
    </div>
  );
  if (page === 'review-results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Review Results</h2>
      {mockCourses.slice(0, 4).map((c, i) => (
        <div key={i} className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div><p className="font-medium">{c.code} - {c.title}</p><p className="text-sm text-muted-foreground">Submitted by {mockLecturers[i % mockLecturers.length].name}</p></div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm"><Eye size={14} /> View</Button>
            <Button size="sm" className="bg-secondary hover:bg-secondary/90"><Check size={14} /> Verify</Button>
            <Button variant="destructive" size="sm"><X size={14} /></Button>
          </div>
        </div>
      ))}
    </div>
  );
  if (page === 'verify-grading') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Verify Grading</h2>
      <DataTable title="CSC101 Results Verification" columns={[
        { key: 'name', label: 'Student' }, { key: 'matric', label: 'Matric' },
        { key: 'gpa', label: 'Score', render: (v: number) => `${Math.floor(v * 20)}%` },
        { key: 'level', label: 'Grade', render: (_: any, row: any) => {
          const s = Math.floor(row.gpa * 20);
          return <span className="font-bold text-primary">{s >= 70 ? 'A' : s >= 60 ? 'B' : s >= 50 ? 'C' : s >= 45 ? 'D' : 'F'}</span>;
        }}
      ]} data={mockTertiaryStudents} />
    </div>
  );
  return <p>Page not found</p>;
}

function CBTExamInterface() {
  const [started, setStarted] = useState(false);
  const [currentQ, setCurrentQ] = useState(0);
  const [answers, setAnswers] = useState<(number | null)[]>(new Array(mockCBTQuestions.length).fill(null));
  const [submitted, setSubmitted] = useState(false);
  const [timeLeft, setTimeLeft] = useState(30 * 60);

  useEffect(() => {
    if (!started || submitted) return;
    const timer = setInterval(() => {
      setTimeLeft(t => {
        if (t <= 1) { setSubmitted(true); clearInterval(timer); return 0; }
        return t - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [started, submitted]);

  const score = answers.reduce((acc, a, i) => acc + (a === mockCBTQuestions[i].answer ? 1 : 0), 0);
  const mins = Math.floor(timeLeft / 60);
  const secs = timeLeft % 60;

  if (submitted) return (
    <div className="max-w-lg mx-auto text-center space-y-4">
      <div className="w-20 h-20 rounded-full bg-secondary/10 flex items-center justify-center mx-auto">
        <Check size={40} className="text-secondary" />
      </div>
      <h2 className="font-display text-2xl font-bold">Exam Submitted!</h2>
      <p className="text-4xl font-display font-bold text-primary">{score}/{mockCBTQuestions.length}</p>
      <p className="text-muted-foreground">You scored {Math.round(score / mockCBTQuestions.length * 100)}%</p>
    </div>
  );

  if (!started) return (
    <div className="max-w-lg mx-auto text-center space-y-4">
      <Monitor size={48} className="mx-auto text-primary" />
      <h2 className="font-display text-2xl font-bold">CSC101 Mid-Semester Test</h2>
      <p className="text-muted-foreground">Duration: 30 minutes • {mockCBTQuestions.length} questions</p>
      <div className="bg-card border border-border rounded-xl p-4 text-left text-sm space-y-2">
        <p>• Questions are auto-submitted when time ends</p>
        <p>• Each question carries equal marks</p>
        <p>• You can navigate between questions</p>
      </div>
      <Button onClick={() => setStarted(true)} className="w-full"><Play size={16} /> Start Exam</Button>
    </div>
  );

  const q = mockCBTQuestions[currentQ];

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center justify-between bg-card border border-border rounded-xl p-3">
        <span className="text-sm font-medium">Q{currentQ + 1}/{mockCBTQuestions.length}</span>
        <span className={`flex items-center gap-1 text-sm font-mono font-bold ${timeLeft < 300 ? 'text-destructive' : 'text-foreground'}`}>
          <Clock size={14} /> {mins}:{secs.toString().padStart(2, '0')}
        </span>
      </div>
      <div className="bg-card border border-border rounded-xl p-6">
        <p className="font-medium mb-4">{q.question}</p>
        <div className="space-y-2">
          {q.options.map((o, i) => (
            <button key={i} onClick={() => { const newA = [...answers]; newA[currentQ] = i; setAnswers(newA); }}
              className={`w-full text-left px-4 py-3 rounded-lg border text-sm transition-colors ${answers[currentQ] === i ? 'border-primary bg-primary/10 font-medium' : 'border-border hover:bg-muted'}`}>
              {String.fromCharCode(65 + i)}) {o}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => setCurrentQ(c => c - 1)} disabled={currentQ === 0}>Previous</Button>
        <div className="flex gap-1">
          {mockCBTQuestions.map((_, i) => (
            <button key={i} onClick={() => setCurrentQ(i)}
              className={`w-7 h-7 rounded text-xs font-medium ${i === currentQ ? 'bg-primary text-primary-foreground' : answers[i] !== null ? 'bg-secondary/20 text-secondary' : 'bg-muted'}`}>{i + 1}</button>
          ))}
        </div>
        {currentQ === mockCBTQuestions.length - 1 ?
          <Button onClick={() => setSubmitted(true)} className="bg-secondary hover:bg-secondary/90">Submit</Button> :
          <Button onClick={() => setCurrentQ(c => c + 1)}>Next</Button>}
      </div>
    </div>
  );
}

function TertiaryStudentDashboard({ page }: { page: string }) {
  const { userName } = useApp();
  if (page === 'dashboard') return (
    <div className="space-y-6">
      <h2 className="font-display text-2xl font-bold">Welcome, {userName}!</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Registered Courses" value="6" icon={<BookOpen size={20} />} color="primary" />
        <StatCard title="Current GPA" value="4.20" icon={<GraduationCap size={20} />} trend="+0.3" trendUp color="secondary" />
        <StatCard title="Fees Status" value="Paid" icon={<CreditCard size={20} />} color="accent" />
        <StatCard title="CBT Exams" value="2 pending" icon={<Monitor size={20} />} color="info" />
      </div>
    </div>
  );
  if (page === 'register-courses') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Course Registration</h2>
      <DataTable columns={[
        { key: 'code', label: 'Code' }, { key: 'title', label: 'Course' }, { key: 'unit', label: 'Units' },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Plus size={14} /> Register</Button> }
      ]} data={mockCourses} />
    </div>
  );
  if (page === 'pay-fees') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Pay School Fees</h2>
      <div className="bg-card border border-border rounded-xl p-6 max-w-md">
        <p className="text-sm text-muted-foreground mb-1">Outstanding Balance</p>
        <p className="text-3xl font-display font-bold text-primary mb-4">₦125,000</p>
        <div className="space-y-3">
          <div><label className="text-sm font-medium">Amount</label><input className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1" defaultValue="125000" /></div>
          <div><label className="text-sm font-medium">Payment Method</label>
            <select className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm mt-1"><option>Bank Transfer</option><option>Card Payment</option><option>REMITA</option></select>
          </div>
          <Button className="w-full">Pay Now</Button>
        </div>
      </div>
    </div>
  );
  if (page === 'cbt-exams') return <CBTExamInterface />;
  if (page === 'results') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">My Results</h2>
      <DataTable columns={[
        { key: 'code', label: 'Course' }, { key: 'title', label: 'Title' }, { key: 'unit', label: 'Units' },
        { key: 'actions', label: 'Grade', render: () => <span className="font-bold text-primary">{['A', 'B', 'A', 'C', 'B'][Math.floor(Math.random() * 5)]}</span> }
      ]} data={mockCourses} />
    </div>
  );
  if (page === 'transcript') return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">Transcript</h2>
        <Button><Download size={16} /> Download Transcript</Button>
      </div>
      <div className="bg-card border border-border rounded-xl p-6">
        <div className="text-center mb-4">
          <p className="font-display font-bold text-lg">UNOFFICIAL TRANSCRIPT</p>
          <p className="text-sm text-muted-foreground">Amaka Obi • 2022/CS/001 • Computer Science</p>
        </div>
        <div className="space-y-4">
          <div>
            <p className="font-semibold text-sm mb-2">200 Level - 1st Semester</p>
            <DataTable columns={[
              { key: 'code', label: 'Code' }, { key: 'title', label: 'Course' }, { key: 'unit', label: 'Units' },
              { key: 'actions', label: 'Grade', render: () => <span className="font-bold text-primary">A</span> }
            ]} data={mockCourses.slice(0, 3)} />
          </div>
          <div className="text-right"><p className="text-sm">Semester GPA: <strong className="text-primary">4.20</strong></p><p className="text-sm">CGPA: <strong className="text-primary">4.20</strong></p></div>
        </div>
      </div>
    </div>
  );
  if (page === 'payment-history') return (
    <div className="space-y-4">
      <h2 className="font-display text-2xl font-bold">Payment History</h2>
      <DataTable columns={[
        { key: 'receipt', label: 'Receipt #' }, { key: 'amount', label: 'Amount', render: (v: number) => `₦${v.toLocaleString()}` },
        { key: 'date', label: 'Date' },
        { key: 'status', label: 'Status', render: (v: string) => <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${v === 'Paid' ? 'bg-secondary/10 text-secondary' : 'bg-accent/10 text-accent'}`}>{v}</span> },
        { key: 'actions', label: '', render: () => <Button variant="outline" size="sm"><Download size={14} /> Receipt</Button> }
      ]} data={mockPayments} />
    </div>
  );
  return <p>Page not found</p>;
}

export default function TertiaryDashboard() {
  const { currentRole } = useApp();

  return (
    <DashboardLayout>
      {(page) => {
        switch (currentRole) {
          case 'vc': return <VCDashboard page={page} />;
          case 'ict-admin': return <ICTAdminDashboard page={page} />;
          case 'accountant': return <TertiaryAccountantDashboard page={page} />;
          case 'faculty-admin': return <FacultyAdminDashboard page={page} />;
          case 'dept-admin': return <DeptAdminDashboard page={page} />;
          case 'lecturer': return <LecturerDashboard page={page} />;
          case 'examiner': return <TertiaryExaminerDashboard page={page} />;
          case 'student': return <TertiaryStudentDashboard page={page} />;
          default: return <p>Unknown role</p>;
        }
      }}
    </DashboardLayout>
  );
}
