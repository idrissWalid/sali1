"use client";

import { ReactNode } from "react";
import { X } from "lucide-react";
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
      <AlertDialogContent style={{ maxWidth }} className="modal-content sm:max-w-none">
        <AlertDialogCancel 
          onClick={onClose}
          aria-label="Fermer la fenêtre"
          className="modal-content__close absolute right-5 top-5 grid size-9 place-items-center rounded-xl opacity-80 transition-all hover:opacity-100 focus-visible:opacity-100 outline-none border-none p-0 m-0 sm:right-7 sm:top-7"
          style={{ color: "var(--text-muted)", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", minWidth: "auto", height: "auto" }}
        >
          <X size={17} strokeWidth={1.8} />
        </AlertDialogCancel>

        <AlertDialogHeader className="modal-content__header flex shrink-0 flex-col space-y-1.5 text-left pr-12">
          <AlertDialogTitle className="text-[19px] font-semibold leading-tight tracking-[-0.025em] sm:text-xl">
            {title}
          </AlertDialogTitle>
        </AlertDialogHeader>
        <AlertDialogDescription className="hidden">Modal dialog</AlertDialogDescription>
        <div className="modal-content__body min-h-0 overflow-y-auto" style={{ color: "var(--text-main)", fontSize: "14px", lineHeight: 1.6 }}>
          {children}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
