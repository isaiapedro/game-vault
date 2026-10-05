import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

const routes: Routes = [
  { path: '', redirectTo: '/library', pathMatch: 'full' },
  {
    path: 'library',
    loadChildren: () => import('./pages/library/library-module').then((m) => m.LibraryModule),
  },
  {
    path: 'wishlist',
    loadChildren: () => import('./pages/wishlist/wishlist-module').then((m) => m.WishlistModule),
  },
  {
    path: 'backlog',
    loadChildren: () => import('./pages/backlog/backlog-module').then((m) => m.BacklogModule),
  },
  {
    path: 'games/:id',
    loadChildren: () =>
      import('./pages/game-detail/game-detail-module').then((m) => m.GameDetailModule),
  },
  {
    path: 'statistics',
    loadChildren: () =>
      import('./pages/statistics/statistics-module').then((m) => m.StatisticsModule),
  },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule],
})
export class AppRoutingModule {}
