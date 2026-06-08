// src/components/admin/UserEditModal.tsx

import type React from "react";
import { useEffect } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/hooks/use-toast";
import { useAdminUpdateUser } from "@/lib/api";
import type { AdminUser, AdminUserUpdatePayload } from "@/types/api";

interface UserEditModalProps {
	user: AdminUser;
	isOpen: boolean;
	onClose: () => void;
}

type FormValues = {
	plan: "free" | "standard" | "pro";
	isActive: boolean;
	role: "admin" | "user" | "affiliate";
	affiliateCommissionRate: number;
};

export const UserEditModal: React.FC<UserEditModalProps> = ({
	user,
	isOpen,
	onClose,
}) => {
	const { user: currentUser } = useAuth();
	const { toast } = useToast();
	const { mutate: updateUser, isPending: isUpdating } = useAdminUpdateUser();

	const { control, handleSubmit, reset } = useForm<FormValues>({
		defaultValues: {
			plan: "free",
			isActive: true,
			role: "user",
			affiliateCommissionRate: 0,
		},
	});

	const watchedRole = useWatch({ control, name: "role" });

	useEffect(() => {
		if (user) {
			reset({
				plan: user.plan,
				isActive: user.isActive,
				role: user.role,
				affiliateCommissionRate: (user.affiliateCommissionRate || 0) * 100,
			});
		}
	}, [user, reset]);

	const onSubmit = (data: FormValues) => {
		const payload: AdminUserUpdatePayload = {};

		if (data.plan !== user.plan) payload.plan = data.plan;
		if (data.isActive !== user.isActive) payload.isActive = data.isActive;
		if (data.role !== user.role) payload.role = data.role;

		if (data.role === "affiliate") {
			// Check if the rate has changed
			if (
				data.affiliateCommissionRate / 100 !==
				(user.affiliateCommissionRate || 0)
			) {
				payload.affiliateCommissionRate = data.affiliateCommissionRate / 100;
			}
		} else {
			// If role is not affiliate, and it was before, we need to clear the rate
			if (user.role === "affiliate") {
				payload.affiliateCommissionRate = null;
			}
		}

		if (Object.keys(payload).length > 0) {
			updateUser(
				{ userId: user.id, payload },
				{
					onSuccess: () => {
						toast({
							title: "Success",
							description: "User updated successfully.",
						});
						onClose();
					},
					onError: (error) => {
						toast({
							title: "Error",
							description: `Failed to update user: ${error.message}`,
							variant: "destructive",
						});
					},
				},
			);
		} else {
			onClose(); // No changes were made
		}
	};

	const isEditingSelf = user.id === currentUser?.id;

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Edit User: {user.username}</DialogTitle>
				</DialogHeader>
				<form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-4">
					<div className="space-y-2">
						<Label>Plan</Label>
						<Controller
							name="plan"
							control={control}
							render={({ field }) => (
								<Select onValueChange={field.onChange} value={field.value}>
									<SelectTrigger>
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="free">Free</SelectItem>
										<SelectItem value="standard">Standard</SelectItem>
										<SelectItem value="pro">Pro</SelectItem>
									</SelectContent>
								</Select>
							)}
						/>
					</div>

					<div className="space-y-2">
						<Label>Role</Label>
						<Controller
							name="role"
							control={control}
							render={({ field }) => (
								<Select
									onValueChange={field.onChange}
									value={field.value}
									disabled={isEditingSelf}
								>
									<SelectTrigger>
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="user">User</SelectItem>
										<SelectItem value="affiliate">Affiliate</SelectItem>
										<SelectItem value="admin">Admin</SelectItem>
									</SelectContent>
								</Select>
							)}
						/>
						{isEditingSelf && (
							<p className="text-xs text-muted-foreground">
								You cannot change your own role.
							</p>
						)}
					</div>

					{watchedRole === "affiliate" && (
						<div className="space-y-2">
							<Label htmlFor="commission-rate">Commission Rate (%)</Label>
							<Controller
								name="affiliateCommissionRate"
								control={control}
								render={({ field }) => (
									<Input
										id="commission-rate"
										type="number"
										{...field}
										onChange={(e) => field.onChange(parseFloat(e.target.value))}
									/>
								)}
							/>
						</div>
					)}

					<div className="flex items-center space-x-2 pt-2">
						<Controller
							name="isActive"
							control={control}
							render={({ field }) => (
								<Switch
									id="is-active"
									checked={field.value}
									onCheckedChange={field.onChange}
								/>
							)}
						/>
						<Label htmlFor="is-active">User is Active</Label>
					</div>

					<DialogFooter>
						<Button type="button" variant="ghost" onClick={onClose}>
							Cancel
						</Button>
						<Button type="submit" disabled={isUpdating}>
							{isUpdating ? "Saving..." : "Save Changes"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
};
