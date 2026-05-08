// Mock data for the school management portal

export const mockStudents = [
  { id: 'STU001', name: 'Adebayo Johnson', class: 'SS2', department: 'Science', email: 'adebayo@school.com', gender: 'Male', status: 'Active' },
  { id: 'STU002', name: 'Chinwe Okafor', class: 'SS1', department: 'Arts', email: 'chinwe@school.com', gender: 'Female', status: 'Active' },
  { id: 'STU003', name: 'Emeka Nwankwo', class: 'JSS3', department: 'Commercial', email: 'emeka@school.com', gender: 'Male', status: 'Active' },
  { id: 'STU004', name: 'Fatima Bello', class: 'SS3', department: 'Science', email: 'fatima@school.com', gender: 'Female', status: 'Active' },
  { id: 'STU005', name: 'Grace Adekunle', class: 'JSS1', department: 'Science', email: 'grace@school.com', gender: 'Female', status: 'Inactive' },
  { id: 'STU006', name: 'Hassan Musa', class: 'SS2', department: 'Arts', email: 'hassan@school.com', gender: 'Male', status: 'Active' },
  { id: 'STU007', name: 'Ibrahim Yusuf', class: 'JSS2', department: 'Commercial', email: 'ibrahim@school.com', gender: 'Male', status: 'Active' },
  { id: 'STU008', name: 'Joy Eze', class: 'SS1', department: 'Science', email: 'joy@school.com', gender: 'Female', status: 'Active' },
];

export const mockTeachers = [
  { id: 'TCH001', name: 'Mr. Olu Adeyemi', subject: 'Mathematics', classes: ['SS1', 'SS2'], email: 'olu@school.com' },
  { id: 'TCH002', name: 'Mrs. Ngozi Ibe', subject: 'English Language', classes: ['JSS3', 'SS1'], email: 'ngozi@school.com' },
  { id: 'TCH003', name: 'Mr. Aliyu Garba', subject: 'Physics', classes: ['SS2', 'SS3'], email: 'aliyu@school.com' },
  { id: 'TCH004', name: 'Mrs. Funke Balogun', subject: 'Chemistry', classes: ['SS1', 'SS2'], email: 'funke@school.com' },
  { id: 'TCH005', name: 'Mr. Peter Obi', subject: 'Biology', classes: ['SS2', 'SS3'], email: 'peter@school.com' },
];

export const mockSubjects = [
  'Mathematics', 'English Language', 'Physics', 'Chemistry', 'Biology',
  'Geography', 'Economics', 'Government', 'Literature', 'Civic Education',
  'Computer Science', 'Agricultural Science', 'Further Mathematics', 'Technical Drawing',
];

export const mockClasses = ['JSS1', 'JSS2', 'JSS3', 'SS1', 'SS2', 'SS3'];

export const mockSessions = [
  { id: 1, name: '2024/2025', status: 'Current' },
  { id: 2, name: '2023/2024', status: 'Completed' },
  { id: 3, name: '2022/2023', status: 'Completed' },
];

export const mockTerms = ['First Term', 'Second Term', 'Third Term'];

export const mockFees = [
  { id: 'FEE001', name: 'School Fees', amount: 45000, term: 'First Term', session: '2024/2025', class: 'SS1' },
  { id: 'FEE002', name: 'School Fees', amount: 45000, term: 'First Term', session: '2024/2025', class: 'SS2' },
  { id: 'FEE003', name: 'School Fees', amount: 35000, term: 'First Term', session: '2024/2025', class: 'JSS1' },
  { id: 'FEE004', name: 'Lab Fee', amount: 5000, term: 'First Term', session: '2024/2025', class: 'SS2' },
];

export const mockPayments = [
  { id: 'PAY001', studentId: 'STU001', studentName: 'Adebayo Johnson', amount: 45000, date: '2024-09-15', status: 'Paid', receipt: 'REC001' },
  { id: 'PAY002', studentId: 'STU002', studentName: 'Chinwe Okafor', amount: 45000, date: '2024-09-20', status: 'Paid', receipt: 'REC002' },
  { id: 'PAY003', studentId: 'STU003', studentName: 'Emeka Nwankwo', amount: 25000, date: '2024-10-01', status: 'Partial', receipt: 'REC003' },
  { id: 'PAY004', studentId: 'STU004', studentName: 'Fatima Bello', amount: 45000, date: '2024-09-18', status: 'Paid', receipt: 'REC004' },
];

export const mockResults = [
  { studentId: 'STU001', subject: 'Mathematics', test1: 18, test2: 15, assignment: 8, exam: 52, total: 93, grade: 'A1' },
  { studentId: 'STU001', subject: 'English', test1: 14, test2: 12, assignment: 7, exam: 45, total: 78, grade: 'B2' },
  { studentId: 'STU001', subject: 'Physics', test1: 16, test2: 14, assignment: 9, exam: 48, total: 87, grade: 'A1' },
  { studentId: 'STU001', subject: 'Chemistry', test1: 12, test2: 13, assignment: 6, exam: 40, total: 71, grade: 'B3' },
  { studentId: 'STU001', subject: 'Biology', test1: 15, test2: 16, assignment: 8, exam: 50, total: 89, grade: 'A1' },
];

// Tertiary data
export const mockFaculties = [
  { id: 'FAC001', name: 'Faculty of Science', dean: 'Prof. Adamu Bello', departments: 5 },
  { id: 'FAC002', name: 'Faculty of Engineering', dean: 'Prof. Chika Obi', departments: 4 },
  { id: 'FAC003', name: 'Faculty of Arts', dean: 'Prof. Amina Yusuf', departments: 6 },
  { id: 'FAC004', name: 'Faculty of Social Sciences', dean: 'Prof. Olu Bakare', departments: 4 },
];

export const mockDepartments = [
  { id: 'DEP001', name: 'Computer Science', faculty: 'Faculty of Science', hod: 'Dr. Kemi Adeola', students: 320 },
  { id: 'DEP002', name: 'Mathematics', faculty: 'Faculty of Science', hod: 'Dr. Musa Ibrahim', students: 180 },
  { id: 'DEP003', name: 'Electrical Engineering', faculty: 'Faculty of Engineering', hod: 'Dr. Tunde Ojo', students: 250 },
  { id: 'DEP004', name: 'English', faculty: 'Faculty of Arts', hod: 'Dr. Binta Abubakar', students: 200 },
];

export const mockCourses = [
  { code: 'CSC101', title: 'Introduction to Computer Science', unit: 3, semester: '1st', department: 'Computer Science' },
  { code: 'CSC201', title: 'Data Structures & Algorithms', unit: 3, semester: '1st', department: 'Computer Science' },
  { code: 'MTH101', title: 'Elementary Mathematics I', unit: 3, semester: '1st', department: 'Mathematics' },
  { code: 'ENG101', title: 'Use of English I', unit: 2, semester: '1st', department: 'English' },
  { code: 'PHY101', title: 'General Physics I', unit: 3, semester: '1st', department: 'Physics' },
];

export const mockLecturers = [
  { id: 'LEC001', name: 'Dr. Kemi Adeola', department: 'Computer Science', courses: ['CSC101', 'CSC201'], email: 'kemi@uni.edu' },
  { id: 'LEC002', name: 'Prof. Musa Ibrahim', department: 'Mathematics', courses: ['MTH101'], email: 'musa@uni.edu' },
  { id: 'LEC003', name: 'Dr. Tunde Ojo', department: 'Electrical Engineering', courses: ['EEG201'], email: 'tunde@uni.edu' },
];

export const mockTertiaryStudents = [
  { id: 'UNI001', name: 'Amaka Obi', matric: '2022/CS/001', department: 'Computer Science', level: '200', gpa: 4.2 },
  { id: 'UNI002', name: 'Bola Adeyemi', matric: '2022/CS/002', department: 'Computer Science', level: '200', gpa: 3.8 },
  { id: 'UNI003', name: 'Chidi Nwosu', matric: '2023/EE/001', department: 'Electrical Engineering', level: '100', gpa: 3.5 },
  { id: 'UNI004', name: 'Dayo Ogunleye', matric: '2021/MA/001', department: 'Mathematics', level: '300', gpa: 4.5 },
];

export const mockCBTExams = [
  { id: 'CBT001', title: 'CSC101 Mid-Semester Test', course: 'CSC101', duration: 30, questions: 30, status: 'Active', department: 'Computer Science' },
  { id: 'CBT002', title: 'MTH101 Quiz 1', course: 'MTH101', duration: 20, questions: 20, status: 'Scheduled', department: 'Mathematics' },
  { id: 'CBT003', title: 'PHY101 Practice Test', course: 'PHY101', duration: 45, questions: 40, status: 'Completed', department: 'Physics' },
];

export const mockCBTQuestions = [
  { id: 1, question: 'What is the binary equivalent of decimal 10?', options: ['1010', '1100', '1001', '0110'], answer: 0 },
  { id: 2, question: 'Which data structure uses FIFO principle?', options: ['Stack', 'Queue', 'Tree', 'Graph'], answer: 1 },
  { id: 3, question: 'What does CPU stand for?', options: ['Central Process Unit', 'Central Processing Unit', 'Computer Personal Unit', 'Central Program Unit'], answer: 1 },
  { id: 4, question: 'Which generation of computers used transistors?', options: ['First', 'Second', 'Third', 'Fourth'], answer: 1 },
  { id: 5, question: 'RAM is a type of?', options: ['Secondary storage', 'Primary memory', 'Output device', 'Input device'], answer: 1 },
];

export const dashboardStats = {
  secondary: {
    totalStudents: 1250,
    totalTeachers: 48,
    totalClasses: 18,
    totalSubjects: 14,
    feesCollected: 28500000,
    feesPending: 8750000,
    passRate: 87.5,
    attendance: 94.2,
  },
  tertiary: {
    totalStudents: 8500,
    totalLecturers: 320,
    totalFaculties: 8,
    totalDepartments: 32,
    feesCollected: 425000000,
    feesPending: 75000000,
    graduationRate: 82.3,
    cbtExamsCreated: 156,
  },
};
