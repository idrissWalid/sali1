"use client";

import { useEffect, ReactNode } from "react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogCancel
} from "./AlertDialog";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  maxWidth?: string;
}

export default function Modal({ isOpen, onClose, title, children, maxWidth = "500px" }: ModalProps) {
  return (
    <AlertDialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent style={{ maxWidth }} className="sm:max-w-none">
        <AlertDialogHeader className="border-b border-[var(--border-muted)] pb-4 mb-4 flex flex-row items-center justify-between">
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogCancel 
            onClick={onClose}
            className="w-8 h-8 rounded-full flex items-center justify-center p-0 mt-0 sm:mt-0 border-none hover:bg-[var(--bubble-ai)] text-[var(--text-muted)] text-xl"
          >
            ×
          </AlertDialogCancel>
        </AlertDialogHeader>
        <AlertDialogDescription className="hidden">Modal dialog</AlertDialogDescription>
        <div style={{ color: "var(--text-main)", overflowY: "auto", maxHeight: "70vh", fontSize: "14px", lineHeight: 1.5 }}>
          {children}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
