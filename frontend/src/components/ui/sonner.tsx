// frontend/src/components/ui/sonner.tsx
// Backward-compatibility adapter: forwards all toast calls to the unified Radix UI toast system

import { toast, useToast } from "@/hooks/use-toast";

const Toaster = () => null;

export { Toaster, toast, useToast };
