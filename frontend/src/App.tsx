/** 路由装配：9 个页面路由 + 全局布局。 */
import { Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import DashboardPage from './pages/DashboardPage';
import GroupsPage from './pages/GroupsPage';
import CreatorWorksPage from './pages/CreatorWorksPage';
import WorkDetailPage from './pages/WorkDetailPage';
import WorkLocalViewPage from './pages/WorkLocalViewPage';
import TagsPage from './pages/TagsPage';
import UnclassifiedPage from './pages/UnclassifiedPage';
import LexiconPage from './pages/LexiconPage';
import SettingsPage from './pages/SettingsPage';
import ArchivePage from './pages/ArchivePage';

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/groups" element={<GroupsPage />} />
        <Route path="/creators/:id" element={<CreatorWorksPage />} />
        <Route path="/works/:id" element={<WorkDetailPage />} />
        <Route path="/works/:id/local" element={<WorkLocalViewPage />} />
        <Route path="/tags" element={<TagsPage />} />
        <Route path="/unclassified" element={<UnclassifiedPage />} />
        <Route path="/archive" element={<ArchivePage />} />
        <Route path="/lexicon" element={<LexiconPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
