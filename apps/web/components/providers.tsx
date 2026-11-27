'use client';

import { Toaster } from '@/components/ui/toast';
import { AuthProvider } from '@/lib/auth';

export function ToasterProvider() {
  return <Toaster />;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      {children}
    </AuthProvider>
  );
}