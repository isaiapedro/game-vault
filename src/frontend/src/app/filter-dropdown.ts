import { ChangeDetectionStrategy, ChangeDetectorRef, Component, ElementRef, EventEmitter, HostListener, Input, Output, QueryList, ViewChild, ViewChildren } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface FilterOption { value: string; label: string }

let nextDropdownId = 0;

@Component({
  selector: 'gv-filter-dropdown', standalone: true, imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="field dropdown-field">
      <span class="dropdown-label" [id]="labelId">{{ label }}</span>
      <button #trigger type="button" class="dropdown-trigger" [class.open]="expanded"
        [attr.aria-label]="label + ': ' + selectedLabel" [attr.aria-expanded]="expanded"
        aria-haspopup="listbox" [attr.aria-controls]="menuId"
        (click)="toggle()" (keydown)="onTriggerKeydown($event)">
        <span>{{ selectedLabel }}</span><span class="dropdown-chevron" aria-hidden="true"></span>
      </button>
      <div *ngIf="expanded" class="dropdown-menu" [id]="menuId" role="listbox" [attr.aria-label]="label">
        <button #optionButton *ngFor="let option of options; let index = index" type="button"
          class="dropdown-option" role="option" [class.selected]="option.value === value"
          [attr.aria-selected]="option.value === value" [attr.tabindex]="index === focusedIndex ? 0 : -1"
          (click)="choose(option.value)" (keydown)="onOptionKeydown($event, index)">
          <span>{{ option.label }}</span><span class="dropdown-check" aria-hidden="true">{{ option.value === value ? '✓' : '' }}</span>
        </button>
      </div>
    </div>
  `,
})
export class FilterDropdown {
  @Input({ required: true }) label = '';
  @Input({ required: true }) options: FilterOption[] = [];
  @Input({ required: true }) value = '';
  @Output() valueChange = new EventEmitter<string>();
  @ViewChild('trigger') trigger!: ElementRef<HTMLButtonElement>;
  @ViewChildren('optionButton') optionButtons!: QueryList<ElementRef<HTMLButtonElement>>;

  readonly menuId = `gv-filter-menu-${++nextDropdownId}`;
  readonly labelId = `${this.menuId}-label`;
  expanded = false;
  focusedIndex = 0;

  constructor(private host: ElementRef<HTMLElement>, private cdr: ChangeDetectorRef) {}

  get selectedLabel(): string {
    return this.options.find(option => option.value === this.value)?.label ?? this.options[0]?.label ?? '';
  }

  toggle(): void { this.expanded ? this.close(false) : this.open(); }

  open(index = this.options.findIndex(option => option.value === this.value)): void {
    if (!this.options.length) return;
    this.focusedIndex = Math.max(0, index);
    this.expanded = true;
    this.cdr.detectChanges();
    this.focusOption();
  }

  close(focusTrigger = true): void {
    this.expanded = false;
    this.cdr.markForCheck();
    if (focusTrigger) this.trigger.nativeElement.focus();
  }

  choose(value: string): void {
    if (value !== this.value) this.valueChange.emit(value);
    this.close();
  }

  onTriggerKeydown(event: KeyboardEvent): void {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      this.open(event.key === 'ArrowUp' ? this.options.length - 1 : this.options.findIndex(option => option.value === this.value));
    } else if (event.key === 'Escape' && this.expanded) {
      event.preventDefault(); this.close();
    }
  }

  onOptionKeydown(event: KeyboardEvent, index: number): void {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      this.focusedIndex = event.key === 'Home' ? 0 : event.key === 'End' ? this.options.length - 1 :
        (index + (event.key === 'ArrowDown' ? 1 : -1) + this.options.length) % this.options.length;
      this.cdr.detectChanges();
      this.focusOption();
    } else if (event.key === 'Escape') {
      event.preventDefault(); this.close();
    } else if (event.key === 'Tab') {
      this.close(false);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); this.choose(this.options[index].value);
    }
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.expanded && !this.host.nativeElement.contains(event.target as Node)) this.close(false);
  }

  private focusOption(): void {
    this.optionButtons.get(this.focusedIndex)?.nativeElement.focus();
  }
}
