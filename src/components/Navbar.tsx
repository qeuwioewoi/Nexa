import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function Navbar() {
  const { user, signOut } = useAuth();

  return (
    <nav className="bg-white shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex">
            <Link to="/" className="flex items-center">
              <span className="text-xl font-bold text-indigo-600">AI Generator</span>
            </Link>
            {user && (
              <div className="ml-10 flex items-center space-x-4">
                <Link to="/" className="text-gray-700 hover:text-indigo-600">
                  Dashboard
                </Link>
                <Link to="/generator" className="text-gray-700 hover:text-indigo-600">
                  Generate
                </Link>
                <Link to="/profile" className="text-gray-700 hover:text-indigo-600">
                  Profile
                </Link>
              </div>
            )}
          </div>
          <div className="flex items-center">
            {user ? (
              <button
                onClick={signOut}
                className="ml-4 px-4 py-2 rounded-md text-white bg-indigo-600 hover:bg-indigo-700"
              >
                Sign Out
              </button>
            ) : (
              <div className="flex space-x-4">
                <Link
                  to="/login"
                  className="px-4 py-2 rounded-md text-indigo-600 hover:text-indigo-700"
                >
                  Login
                </Link>
                <Link
                  to="/register"
                  className="px-4 py-2 rounded-md text-white bg-indigo-600 hover:bg-indigo-700"
                >
                  Register
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}