// src/components/strategy-editor/SymbolCombobox.tsx

import { Check, ChevronsUpDown, Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
} from "@/components/ui/command";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import { useDebounce } from "@/hooks/useDebounce";
import { useGetAvailableSymbols } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SymbolComboboxProps {
	value: string;
	onChange: (value: string) => void;
	disabled?: boolean;
}

export const SymbolCombobox: React.FC<SymbolComboboxProps> = ({
	value,
	onChange,
	disabled,
}) => {
	const [open, setOpen] = useState(false);
	const [searchQuery, setSearchQuery] = useState("");
	const debouncedSearchQuery = useDebounce(searchQuery, 300);

	// We pass `open` as the `enabled` option.
	// When the popover opens (open === true), the hook is activated
	// and makes a request even if the search string is empty.
	const { data: availableSymbols, isLoading } = useGetAvailableSymbols(
		debouncedSearchQuery,
		{ enabled: open },
	);

	const isSearchQueryInList = availableSymbols?.some(
		(s) => s.toUpperCase() === searchQuery.toUpperCase(),
	);

	return (
		<Popover open={open} onOpenChange={setOpen}>
			<PopoverTrigger asChild>
				<Button
					variant="outline"
					role="combobox"
					aria-expanded={open}
					className="w-full justify-between"
					disabled={disabled}
				>
					{value || "Select symbol..."}
					<ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
				</Button>
			</PopoverTrigger>
			<PopoverContent className="w-[--radix-popover-trigger-width] p-0">
				<Command>
					<CommandInput
						placeholder="Search symbol..."
						value={searchQuery}
						onValueChange={setSearchQuery}
					/>
					<CommandList>
						{isLoading && (
							<div className="p-2 flex items-center justify-center">
								<Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
							</div>
						)}

						{!isLoading && searchQuery && !isSearchQueryInList && (
							<CommandGroup>
								<CommandItem
									value={searchQuery}
									onSelect={() => {
										onChange(searchQuery.trim().toUpperCase());
										setOpen(false);
										setSearchQuery("");
									}}
									className="cursor-pointer"
								>
									<Plus className="mr-2 h-4 w-4 text-primary" />
									<span>
										Use "<strong>{searchQuery.toUpperCase()}</strong>"
									</span>
								</CommandItem>
							</CommandGroup>
						)}

						<CommandEmpty>No symbols found.</CommandEmpty>

						{/* Adding a check that we are not in a loading state */}
						{!isLoading && availableSymbols && availableSymbols.length > 0 && (
							<CommandGroup>
								{availableSymbols.map((symbol) => (
									<CommandItem
										key={symbol}
										value={symbol}
										onSelect={(currentValue) => {
											onChange(currentValue.toUpperCase());
											setOpen(false);
											setSearchQuery("");
										}}
									>
										<Check
											className={cn(
												"mr-2 h-4 w-4",
												value.toUpperCase() === symbol.toUpperCase()
													? "opacity-100"
													: "opacity-0",
											)}
										/>
										{symbol}
									</CommandItem>
								))}
							</CommandGroup>
						)}
					</CommandList>
				</Command>
			</PopoverContent>
		</Popover>
	);
};
