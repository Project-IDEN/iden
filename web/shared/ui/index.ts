export { cn } from "./cn";
export { useDocumentTitle } from "./use-document-title";

/* shadcn primitives, unmodified except where DESIGN.md is explicit about a
   value — see the note at the top of each adapted file. */
export { Alert, AlertTitle, AlertDescription } from "./alert";
export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./alert-dialog";
export { Badge, badgeVariants } from "./badge";
export {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "./breadcrumb";
export { Button, buttonVariants, type ButtonProps } from "./button";
export {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./card";
export { Checkbox } from "./checkbox";
export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./dialog";
export {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./dropdown-menu";
export { Input } from "./input";
export { Label } from "./label";
export { Popover, PopoverContent, PopoverTrigger } from "./popover";
export { Progress } from "./progress";
export { RadioGroup, RadioGroupItem } from "./radio-group";
export { ScrollArea, ScrollBar } from "./scroll-area";
export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "./select";
export { Separator } from "./separator";
export { Skeleton } from "./skeleton";
export { Switch } from "./switch";
export {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "./table";
export { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";
export { Textarea } from "./textarea";
export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

/* Compositions of the above. Each exists because it carries a decision — a
   wording, a responsive behaviour, a rule about what may be shown — rather than
   because shadcn was missing a box. */
export { Avatar } from "./avatar";
export { ConfirmDialog, SecretRevealOnce } from "./confirm-dialog";
export { DataTable, Pagination, type Column } from "./data-table";
export { DateRangePicker } from "./calendar";
export type { DateRange } from "react-day-picker";
export { EmptyState, ErrorState, Spinner } from "./feedback";
export { Field, SearchInput } from "./field";
export { StatusDot } from "./status-dot";
export { RowCard, Row, ROW_CARD } from "./rows";
export { ScopeChip, ProvenanceRow, ProvenanceTrace, type ResolvedScope } from "./provenance";
export { Brand } from "./brand";
export { Logo } from "./logo";
export { Mark } from "./mark";
